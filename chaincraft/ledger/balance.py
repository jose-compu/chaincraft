"""Account/balance ledger model.

State is a mapping of account -> integer balance plus a per-account nonce. This
mirrors the Ethereum-style account model and is the default for most users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .base import (
    FeeCharge,
    LedgerError,
    LedgerModel,
    LedgerState,
    compute_tx_id,
)

#: Synthetic account that collects tips when no miner is supplied. Keeping the
#: value here (rather than discarding it) preserves value conservation in tests.
FEE_POOL_ACCOUNT = "__fees__"


@dataclass(frozen=True)
class Transaction:
    """A signed value transfer in the account model.

    ``data`` is an opaque byte payload (notes, hashes, app messages). It is
    stored and forwarded by the ledger but **not executed** — smart contracts
    are out of scope for 0.6.0. Payload size may incur a configurable fee via
    :mod:`chaincraft.fees.payload`.
    """

    sender: str
    recipient: str
    amount: int
    fee: int
    nonce: int = 0
    asset: str = "native"
    data: bytes = b""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def tx_id(self) -> str:
        return compute_tx_id(
            {
                "sender": self.sender,
                "recipient": self.recipient,
                "amount": self.amount,
                "fee": self.fee,
                "nonce": self.nonce,
                "asset": self.asset,
                "data": self.data.hex(),
            }
        )


@dataclass
class BalanceState(LedgerState):
    balances: Dict[str, int] = field(default_factory=dict)
    nonces: Dict[str, int] = field(default_factory=dict)
    burned: int = 0

    def copy(self) -> "BalanceState":
        return BalanceState(
            balances=dict(self.balances),
            nonces=dict(self.nonces),
            burned=self.burned,
        )

    def total_supply(self) -> int:
        return sum(self.balances.values())

    def balance_of(self, account: str) -> int:
        return self.balances.get(account, 0)

    def to_snapshot(self) -> Mapping[str, Any]:
        return {
            "model": "balance",
            "balances": dict(self.balances),
            "nonces": dict(self.nonces),
            "burned": self.burned,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "BalanceState":
        return cls(
            balances=dict(snapshot.get("balances", {})),
            nonces=dict(snapshot.get("nonces", {})),
            burned=int(snapshot.get("burned", 0)),
        )


class BalanceLedgerModel(LedgerModel):
    """Account-based ledger with optional nonce enforcement."""

    name = "balance"

    def __init__(self, *, enforce_nonce: bool = True, allow_overdraft: bool = False):
        self.enforce_nonce = enforce_nonce
        self.allow_overdraft = allow_overdraft

    def genesis_state(
        self, allocations: Optional[Mapping[str, int]] = None
    ) -> BalanceState:
        balances = {acct: int(amt) for acct, amt in (allocations or {}).items()}
        return BalanceState(balances=balances)

    def validate(self, tx: Transaction, state: BalanceState) -> None:
        if tx.amount < 0:
            raise LedgerError("amount must be non-negative")
        if tx.fee < 0:
            raise LedgerError("fee must be non-negative")
        if self.enforce_nonce:
            expected = state.nonces.get(tx.sender, 0)
            if tx.nonce != expected:
                raise LedgerError(
                    f"bad nonce for {tx.sender}: expected {expected}, got {tx.nonce}"
                )
        if not self.allow_overdraft:
            required = tx.amount + tx.fee
            if state.balance_of(tx.sender) < required:
                raise LedgerError(
                    f"insufficient balance for {tx.sender}: "
                    f"has {state.balance_of(tx.sender)}, needs {required}"
                )

    def apply_tx(
        self,
        tx: Transaction,
        state: BalanceState,
        *,
        charge: Optional[FeeCharge] = None,
        miner: Optional[str] = None,
    ) -> BalanceState:
        self.validate(tx, state)
        if charge is None:
            charge = FeeCharge(charged=tx.fee, burned=0, tip=tx.fee)

        new_state = state.copy()
        new_state.balances[tx.sender] = (
            new_state.balance_of(tx.sender) - tx.amount - charge.charged
        )
        new_state.balances[tx.recipient] = (
            new_state.balance_of(tx.recipient) + tx.amount
        )

        tip_account = miner if miner is not None else FEE_POOL_ACCOUNT
        if charge.tip:
            new_state.balances[tip_account] = (
                new_state.balance_of(tip_account) + charge.tip
            )
        if charge.burned:
            new_state.burned += charge.burned

        if self.enforce_nonce:
            new_state.nonces[tx.sender] = new_state.nonces.get(tx.sender, 0) + 1
        return new_state

    def _credit_coinbase(
        self, state: BalanceState, miner: Optional[str], reward: int
    ) -> BalanceState:
        new_state = state.copy()
        account = miner if miner is not None else FEE_POOL_ACCOUNT
        new_state.balances[account] = new_state.balance_of(account) + reward
        return new_state
