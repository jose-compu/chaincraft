"""UTXO (unspent transaction output) ledger model.

State is a set of unspent outputs keyed by id. A transaction consumes existing
outputs (inputs) and creates new ones (outputs); the structural fee is
``sum(inputs) - sum(outputs)``. Because the fee is fixed by the output
structure, fee policies may only split that fee into burned/tip portions, not
re-price it (unlike the account model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from .base import (
    FeeCharge,
    LedgerError,
    LedgerModel,
    LedgerState,
    compute_tx_id,
)


@dataclass(frozen=True)
class UTXOOutput:
    owner: str
    amount: int


@dataclass(frozen=True)
class UTXOTransaction:
    """Spends ``inputs`` (utxo ids) and creates ``outputs``.

    ``data`` is an opaque attachment (not executed). Fee policies may price it.
    """

    inputs: Tuple[str, ...]
    outputs: Tuple[UTXOOutput, ...]
    fee: int
    data: bytes = b""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def tx_id(self) -> str:
        return compute_tx_id(
            {
                "inputs": list(self.inputs),
                "outputs": [[o.owner, o.amount] for o in self.outputs],
                "fee": self.fee,
                "data": self.data.hex(),
            }
        )


@dataclass
class UTXOState(LedgerState):
    #: utxo_id -> {"owner": str, "amount": int}
    utxos: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    burned: int = 0

    def copy(self) -> "UTXOState":
        return UTXOState(
            utxos={k: dict(v) for k, v in self.utxos.items()},
            burned=self.burned,
        )

    def total_supply(self) -> int:
        return sum(u["amount"] for u in self.utxos.values())

    def balance_of(self, owner: str) -> int:
        return sum(u["amount"] for u in self.utxos.values() if u["owner"] == owner)

    def to_snapshot(self) -> Mapping[str, Any]:
        return {
            "model": "utxo",
            "utxos": {k: dict(v) for k, v in self.utxos.items()},
            "burned": self.burned,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "UTXOState":
        return cls(
            utxos={k: dict(v) for k, v in snapshot.get("utxos", {}).items()},
            burned=int(snapshot.get("burned", 0)),
        )


class UTXOLedgerModel(LedgerModel):
    name = "utxo"

    def genesis_state(
        self, allocations: Optional[Mapping[str, int]] = None
    ) -> UTXOState:
        utxos: Dict[str, Dict[str, Any]] = {}
        for owner, amount in (allocations or {}).items():
            utxos[f"genesis:{owner}"] = {"owner": owner, "amount": int(amount)}
        return UTXOState(utxos=utxos)

    def validate(self, tx: UTXOTransaction, state: UTXOState) -> None:
        if tx.fee < 0:
            raise LedgerError("fee must be non-negative")
        if not tx.inputs:
            raise LedgerError("transaction must spend at least one input")
        seen = set()
        input_total = 0
        for utxo_id in tx.inputs:
            if utxo_id in seen:
                raise LedgerError(f"duplicate input {utxo_id}")
            seen.add(utxo_id)
            if utxo_id not in state.utxos:
                raise LedgerError(f"input {utxo_id} does not exist or is spent")
            input_total += state.utxos[utxo_id]["amount"]
        output_total = 0
        for out in tx.outputs:
            if out.amount < 0:
                raise LedgerError("output amount must be non-negative")
            output_total += out.amount
        if input_total != output_total + tx.fee:
            raise LedgerError(
                f"value mismatch: inputs {input_total} != outputs {output_total} "
                f"+ fee {tx.fee}"
            )

    def apply_tx(
        self,
        tx: UTXOTransaction,
        state: UTXOState,
        *,
        charge: Optional[FeeCharge] = None,
        miner: Optional[str] = None,
    ) -> UTXOState:
        self.validate(tx, state)
        if charge is None:
            charge = FeeCharge(charged=tx.fee, burned=0, tip=tx.fee)
        if charge.charged != tx.fee:
            raise LedgerError(
                "UTXO ledger cannot re-price fees: "
                f"charge.charged ({charge.charged}) must equal structural fee "
                f"({tx.fee})"
            )

        new_state = state.copy()
        for utxo_id in tx.inputs:
            del new_state.utxos[utxo_id]
        for index, out in enumerate(tx.outputs):
            new_state.utxos[f"{tx.tx_id}:{index}"] = {
                "owner": out.owner,
                "amount": out.amount,
            }
        if charge.tip:
            tip_owner = miner if miner is not None else "__fees__"
            new_state.utxos[f"{tx.tx_id}:tip"] = {
                "owner": tip_owner,
                "amount": charge.tip,
            }
        if charge.burned:
            new_state.burned += charge.burned
        return new_state

    def _credit_coinbase(
        self, state: UTXOState, miner: Optional[str], reward: int
    ) -> UTXOState:
        new_state = state.copy()
        owner = miner if miner is not None else "__fees__"
        coinbase_id = compute_tx_id({"coinbase": owner, "reward": reward,
                                     "supply": state.total_supply()})
        new_state.utxos[f"coinbase:{coinbase_id}"] = {"owner": owner,
                                                      "amount": reward}
        return new_state
