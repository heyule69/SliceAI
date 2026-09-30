# Vendored from ZFTurbo/Music-Source-Separation-Training, BandIt model.
# SliceAI changes: local imports, inference-only nn.Module, MIDI formulas.
# See LICENSE-MIT.txt, LICENSE-Apache-2.0.txt and NOTICE.txt.
from .bsrnn.wrapper import (
    MultiMaskMultiSourceBandSplitRNNSimple,
)
