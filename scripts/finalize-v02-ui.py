from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'src/fine.ts';s=p.read_text(encoding='utf-8')
s=s.replace('<button class="primary-button" id="fineExport"','<button class="primary-button" id="fineConfirm" data-fine-action="confirm">确认并预览</button><button class="secondary-button" id="fineExport"')
s=s.replace("  $<HTMLButtonElement>('fineExport').disabled=busy||!v?.confirmed;", "  $<HTMLButtonElement>('fineExport').disabled=busy||!v?.confirmed;\n  $<HTMLButtonElement>('fineConfirm').disabled=busy||!v;\n  $('fineConfirm').textContent=v?.confirmed?'生成预览':'确认并预览';")
s=s.replace('<button class="primary-button" data-fine-action="confirm" ${busy?\'disabled\':\'\'}>${v.confirmed?\'重新生成预览\':\'确认方案并预览\'}</button>','')
p.write_text(s,encoding='utf-8')
p=root/'src/fine.css';s=p.read_text(encoding='utf-8');s+='\n.fine-screen{max-height:300px}.fine-toolbar h2{min-width:0}.fine-toolbar .primary-button,.fine-toolbar .secondary-button{padding-left:10px;padding-right:10px}\n'
p.write_text(s,encoding='utf-8')
