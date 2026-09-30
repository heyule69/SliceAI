#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use serde_json::{json, Value};
use std::{fs, io::{BufRead, BufReader, Write}, path::PathBuf, process::{Command, Stdio}, sync::{mpsc, Arc, Mutex, atomic::{AtomicU64, Ordering}}};
use tauri::{Emitter, Manager};

#[cfg(windows)]
use std::os::windows::{io::AsRawHandle, process::CommandExt};

struct Runtime {
    data: PathBuf,
    worker: PathBuf,
    work_lock: Mutex<()>,
    script: Option<PathBuf>,
    sender: mpsc::Sender<(u64, Value)>,
    queue: Mutex<Vec<Value>>,
    queue_revision: AtomicU64,
    next_job: AtomicU64,
    window_size: Mutex<(f64, f64)>,
    #[cfg(windows)]
    job: usize,
}

// Communication errors must also stop the owned child before persisted state is
// recovered; otherwise it could keep writing progress after being marked stopped.
struct WorkerProcess(std::process::Child);
impl std::ops::Deref for WorkerProcess {
    type Target = std::process::Child;
    fn deref(&self) -> &Self::Target { &self.0 }
}
impl std::ops::DerefMut for WorkerProcess {
    fn deref_mut(&mut self) -> &mut Self::Target { &mut self.0 }
}
impl Drop for WorkerProcess {
    fn drop(&mut self) { let _ = self.0.kill(); let _ = self.0.wait(); }
}

fn queue_snapshot(runtime: &Runtime) -> Result<Value, String> {
    let queue = runtime.queue.lock().map_err(|_| "后台队列状态异常，请重新打开程序。")?;
    let mut position = 0;
    let entries: Vec<Value> = queue.iter().map(|entry| {
        let mut entry = entry.clone();
        if entry["status"] == "queued" { position += 1; entry["position"] = json!(position); }
        else { entry["position"] = json!(0); }
        entry
    }).collect();
    Ok(json!({"type":"queue","queue":entries,"queue_revision":runtime.queue_revision.load(Ordering::Relaxed)}))
}

fn emit_queue(app: &tauri::AppHandle, runtime: &Runtime) {
    if let Ok(snapshot) = queue_snapshot(runtime) { let _ = app.emit("worker-event", snapshot); }
}

#[tauri::command]
fn queue_state(runtime: tauri::State<'_, Arc<Runtime>>) -> Result<Value, String> {
    queue_snapshot(&runtime)
}

fn queue_job(app: &tauri::AppHandle, runtime: &Runtime, request: Value) -> Result<(), String> {
    let id = runtime.next_job.fetch_add(1, Ordering::Relaxed);
    {
        let mut queue = runtime.queue.lock().map_err(|_| "后台队列状态异常，请重新打开程序。")?;
        queue.push(json!({"id":id,"cmd":request["cmd"],"task_id":request["task_id"],"project_id":request["project_id"],"status":"queued"}));
        runtime.queue_revision.fetch_add(1, Ordering::Relaxed);
    }
    emit_queue(app, runtime);
    if runtime.sender.send((id, request)).is_err() {
        if let Ok(mut queue) = runtime.queue.lock() { queue.retain(|entry| entry["id"] != id); runtime.queue_revision.fetch_add(1, Ordering::Relaxed); }
        emit_queue(app, runtime);
        return Err("后台队列不可用，请重新打开程序。".into());
    }
    Ok(())
}

fn change_queue(app: &tauri::AppHandle, runtime: &Runtime, id: u64, running: bool) {
    if let Ok(mut queue) = runtime.queue.lock() {
        if running {
            if let Some(entry) = queue.iter_mut().find(|entry| entry["id"] == id) { entry["status"] = json!("running"); }
        } else { queue.retain(|entry| entry["id"] != id); }
        runtime.queue_revision.fetch_add(1, Ordering::Relaxed);
    }
    emit_queue(app, runtime);
}

fn grant_assets(app: &tauri::AppHandle, value: &Value) {
    match value {
        Value::Object(map) => for (key, value) in map {
            if ["thumbnail", "preview", "path"].contains(&key.as_str()) {
                if let Some(path) = value.as_str() {
                    let p = PathBuf::from(path);
                    if p.is_file() { let _ = app.asset_protocol_scope().allow_file(&p); }
                }
            }
            grant_assets(app, value);
        },
        Value::Array(items) => for item in items { grant_assets(app, item); },
        _ => {}
    }
}

fn worker_call(app: &tauri::AppHandle, runtime: &Runtime, mut request: Value) -> Result<Value, String> {
    let heavy = ["preview_compatible", "run", "export", "recheck", "delete_task", "edit_auto", "edit_chat", "edit_confirm", "edit_preview", "edit_export", "edit_audio_sample", "edit_source_preview"];
    let _work_guard = if heavy.contains(&request["cmd"].as_str().unwrap_or("")) { Some(runtime.work_lock.lock().map_err(|_| "处理队列异常，请重新打开程序。")?) } else { None };
    request["_data_dir"] = json!(runtime.data.to_string_lossy());
    let mut command = Command::new(&runtime.worker);
    if let Some(script) = &runtime.script { command.arg(script); }
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    command.env("PYTHONUTF8", "1").env("PYTHONIOENCODING", "utf-8");
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = WorkerProcess(command.spawn().map_err(|e| format!("无法启动处理引擎：{e}"))?);
    #[cfg(windows)]
    unsafe {
        if windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(runtime.job as _, child.as_raw_handle() as _) == 0 {
            let _ = child.kill();
            return Err("无法为处理进程建立退出保护，已停止启动。".into());
        }
    }
    if let Some(mut input) = child.stdin.take() {
        writeln!(input, "{}", request).map_err(|e| format!("处理引擎通信失败：{e}"))?;
    }
    let output = child.stdout.take().ok_or("无法读取处理引擎输出")?;
    let mut result = None;
    let mut error = None;
    for line in BufReader::new(output).lines() {
        let line = line.map_err(|e| format!("读取进度失败：{e}"))?;
        if let Ok(value) = serde_json::from_str::<Value>(&line) {
            if let Some(event) = value.get("event") {
                grant_assets(app, event);
                let _ = app.emit("worker-event", event);
            }
            if let Some(value) = value.get("result") { result = Some(value.clone()); }
            if let Some(value) = value.get("error").and_then(Value::as_str) { error = Some(value.to_owned()); }
        }
    }
    let status = child.wait().map_err(|e| e.to_string())?;
    if let Some(error) = error { return Err(error); }
    if !status.success() { return Err("处理引擎意外退出，请重试；已保存的结果不会丢失。".into()); }
    let result = result.ok_or("处理引擎没有返回结果")?;
    grant_assets(app, &result);
    Ok(result)
}

#[tauri::command]
async fn call(app: tauri::AppHandle, runtime: tauri::State<'_, Arc<Runtime>>, request: Value) -> Result<Value, String> {
    let allowed = ["state", "probe", "save_settings", "api_test", "create_task", "retry_task", "delete_task", "cancel_task", "preview", "preview_compatible", "reveal", "edit_create", "edit_get", "edit_source", "edit_cancel", "edit_prepare", "edit_abandon", "edit_options", "relocate"];
    if !allowed.contains(&request["cmd"].as_str().unwrap_or("")) { return Err("不支持的操作".into()); }
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || worker_call(&app, &runtime, request)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn enqueue(app: tauri::AppHandle, runtime: tauri::State<'_, Arc<Runtime>>, request: Value) -> Result<(), String> {
    let cmd = request["cmd"].as_str().unwrap_or("");
    if !["run", "export", "recheck", "install_model", "edit_chat", "edit_auto", "edit_update", "edit_restore", "edit_confirm", "edit_preview", "edit_export", "edit_audio_sample", "edit_source_preview"].contains(&cmd) { return Err("不支持的后台任务".into()); }
    queue_job(&app, &runtime, request)
}

#[tauri::command]
async fn reveal(app: tauri::AppHandle, runtime: tauri::State<'_, Arc<Runtime>>, task_id: Option<String>) -> Result<(), String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let result = worker_call(&app, &runtime, json!({"cmd":"reveal","task_id":task_id}))?;
        let path = result["path"].as_str().ok_or("目标不存在")?;
        #[cfg(windows)]
        { let mut command = Command::new("explorer.exe");
          if result["is_file"].as_bool().unwrap_or(false) { command.arg(format!("/select,{path}")); }
          else { command.arg(path); }
          command.spawn().map_err(|e| e.to_string())?;
        }
        Ok(())
    }).await.map_err(|e| e.to_string())?
}

#[cfg(windows)]
fn create_job() -> Result<usize, String> {
    use windows_sys::Win32::System::JobObjects::*;
    unsafe {
        let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if handle.is_null() { return Err("无法创建处理进程管理器".into()); }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(handle, JobObjectExtendedLimitInformation, &info as *const _ as _, std::mem::size_of_val(&info) as u32) == 0 {
            windows_sys::Win32::Foundation::CloseHandle(handle);
            return Err("无法设置处理进程管理器".into());
        }
        Ok(handle as usize)
    }
}

fn main() {
    // A second instance must not interrupt or rewrite the first instance's tasks.
    #[cfg(windows)]
    let _instance_mutex = unsafe {
        let name: Vec<u16> = "Local\\SliceAI.Desktop.0.1\0".encode_utf16().collect();
        let handle = windows_sys::Win32::System::Threading::CreateMutexW(std::ptr::null(), 0, name.as_ptr());
        if handle.is_null() || windows_sys::Win32::Foundation::GetLastError() == 183 { return; }
        handle
    };
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data = app.path().app_local_data_dir()?;
            fs::create_dir_all(&data)?;
            let _ = fs::remove_file(data.join("STOP"));
            let saved_size = fs::read_to_string(data.join("window.json")).ok()
                .and_then(|text| serde_json::from_str::<Value>(&text).ok())
                .and_then(|value| Some((value["width"].as_f64()?, value["height"].as_f64()?)))
                .filter(|(w,h)| w.is_finite() && h.is_finite() && (960.0..=7680.0).contains(w) && (640.0..=4320.0).contains(h))
                .unwrap_or((1090.0, 720.0));
            let mut window_size = saved_size;
            if let Some(window) = app.get_webview_window("main") {
                if let Ok(Some(monitor)) = window.current_monitor() {
                    let scale = monitor.scale_factor();
                    window_size.0 = window_size.0.min((monitor.size().width as f64 / scale - 24.0).max(960.0));
                    window_size.1 = window_size.1.min((monitor.size().height as f64 / scale - 80.0).max(640.0));
                }
                window.set_size(tauri::LogicalSize::new(window_size.0, window_size.1))?;
                window.center()?;
                window.show()?;
            }
            let (sender, receiver) = mpsc::channel::<(u64, Value)>();
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
            let (worker, script) = if cfg!(debug_assertions) {
                (root.join(".venv/Scripts/python.exe"), Some(root.join("backend/service.py")))
            } else { (app.path().resource_dir()?.join("worker/sliceai-worker.exe"), None) };
            let runtime = Arc::new(Runtime { data, worker, script, sender, queue: Mutex::new(Vec::new()), queue_revision: AtomicU64::new(0), next_job: AtomicU64::new(1), work_lock: Mutex::new(()), window_size: Mutex::new(window_size),
                #[cfg(windows)] job: create_job().map_err(std::io::Error::other)?,
            });
            app.manage(runtime.clone());
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                match worker_call(&handle, &runtime, json!({"cmd":"bootstrap"})) {
                    Ok(initial) => {
                        if let Some(tasks) = initial["tasks"].as_array() {
                            for task in tasks { if task["status"] == "queued" {
                                let _ = queue_job(&handle, &runtime, json!({"cmd":"run","task_id":task["id"]}));
                            }}
                        }
                        let _ = handle.emit("backend-ready", initial);
                    },
                    Err(error) => { let _ = handle.emit("worker-event", json!({"type":"error","message":error})); }
                }
                for (id, request) in receiver {
                    change_queue(&handle, &runtime, id, true);
                    match worker_call(&handle, &runtime, request.clone()) {
                        Ok(result) => { let _ = handle.emit("worker-event", json!({"type":"finished","cmd":request["cmd"],"task_id":request["task_id"],"project_id":request["project_id"],"result":result})); }
                        Err(error) => {
                            // Recover only the failed operation. Bootstrap would interrupt unrelated jobs.
                            let recovery = worker_call(&handle, &runtime, json!({"cmd":"recover_failure","original_cmd":request["cmd"],"task_id":request["task_id"],"project_id":request["project_id"],"message":error}));
                            let (state, message) = match recovery {
                                Ok(state) => (state, error),
                                Err(recovery_error) => (Value::Null, format!("{error} 状态恢复失败，请重新打开程序：{recovery_error}")),
                            };
                            let _ = handle.emit("worker-event", json!({"type":"error","cmd":request["cmd"],"task_id":request["task_id"],"project_id":request["project_id"],"message":message,"state":state}));
                        }
                    }
                    change_queue(&handle, &runtime, id, false);
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Resized(size) = event {
                // Keep normal dimensions in memory; minimized/maximized sizes must not replace them.
                if size.width == 0 || size.height == 0 || window.is_maximized().unwrap_or(true) || window.is_minimized().unwrap_or(true) { return; }
                if let (Some(runtime), Ok(scale)) = (window.app_handle().try_state::<Arc<Runtime>>(), window.scale_factor()) {
                    let (width, height) = (size.width as f64 / scale, size.height as f64 / scale);
                    if width >= 960.0 && height >= 640.0 {
                        if let Ok(mut saved) = runtime.window_size.lock() { *saved = (width, height); }
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![call, enqueue, queue_state, reveal])
        .build(tauri::generate_context!())
        .expect("SliceAI 无法启动")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
                let runtime = app.state::<Arc<Runtime>>();
                let _ = fs::write(runtime.data.join("STOP"), b"stop");
                if let Ok(size) = runtime.window_size.lock() {
                    let path = runtime.data.join("window.json");
                    let temporary = runtime.data.join("window.json.tmp");
                    if fs::write(&temporary, json!({"width":size.0,"height":size.1}).to_string()).is_ok() {
                        let _ = fs::rename(temporary, path);
                    }
                };
            }
        });
}
