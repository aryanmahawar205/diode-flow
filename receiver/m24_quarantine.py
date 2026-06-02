"""Transfer state machine and quarantine gate."""
from __future__ import annotations
import logging
import time
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TransferState(Enum):
    RECEIVING  = "receiving"
    DECODING   = "decoding"
    VERIFYING  = "verifying"
    QUARANTINE = "quarantine"
    ACCEPTED   = "accepted"
    FAILED     = "failed"
    EXPIRED    = "expired"


@dataclass
class TransferRecord:
    transfer_id : str
    state       : TransferState = TransferState.RECEIVING
    created_at  : float = field(default_factory=time.time)
    error       : str   = ""

    def transition(self, new_state: TransferState, error: str = "") -> None:
        logger.info(f"[{self.transfer_id[:8]}] {self.state.value} → {new_state.value}"
                    + (f" ({error})" if error else ""))
        self.state = new_state
        self.error = error
