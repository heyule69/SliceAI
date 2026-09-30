# Vendored from ZFTurbo/Music-Source-Separation-Training, BandIt model.
# SliceAI changes: local imports, inference-only nn.Module, MIDI formulas.
# See LICENSE-MIT.txt, LICENSE-Apache-2.0.txt and NOTICE.txt.
from abc import ABC
from typing import Iterable, Mapping, Union

from torch import nn

from bandit.bsrnn.bandsplit import BandSplitModule
from bandit.bsrnn.tfmodel import (
    SeqBandModellingModule,
    TransformerTimeFreqModule,
)


class BandsplitCoreBase(nn.Module, ABC):
    band_split: nn.Module
    tf_model: nn.Module
    mask_estim: Union[nn.Module, Mapping[str, nn.Module], Iterable[nn.Module]]

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def mask(x, m):
        return x * m
