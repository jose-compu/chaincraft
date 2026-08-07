"""Pluggable ledger models (Chaincraft 0.6.0).

Choose the economic substrate for a blockchain transparently::

    from chaincraft.ledger import BalanceLedgerModel, UTXOLedgerModel

    ledger = BalanceLedgerModel()              # account/balance model
    state = ledger.genesis_state({"alice": 100})

    from chaincraft.ledger import Transaction
    tx = Transaction(sender="alice", recipient="bob", amount=10, fee=1)
    state = ledger.apply_tx(tx, state, miner="carol")
"""

from .base import (
    FeeCharge,
    LedgerError,
    LedgerModel,
    LedgerState,
    compute_tx_id,
)
from .balance import BalanceLedgerModel, BalanceState, Transaction, FEE_POOL_ACCOUNT
from .utxo import UTXOLedgerModel, UTXOState, UTXOTransaction, UTXOOutput

#: Name -> model class, for configuration-driven selection.
LEDGER_MODELS = {
    BalanceLedgerModel.name: BalanceLedgerModel,
    UTXOLedgerModel.name: UTXOLedgerModel,
}


def get_ledger_model(name: str, **kwargs) -> LedgerModel:
    """Instantiate a ledger model by its registered ``name``."""
    try:
        cls = LEDGER_MODELS[name]
    except KeyError:
        raise LedgerError(
            f"unknown ledger model {name!r}; available: {sorted(LEDGER_MODELS)}"
        )
    return cls(**kwargs)


__all__ = [
    "FeeCharge",
    "LedgerError",
    "LedgerModel",
    "LedgerState",
    "compute_tx_id",
    "BalanceLedgerModel",
    "BalanceState",
    "Transaction",
    "FEE_POOL_ACCOUNT",
    "UTXOLedgerModel",
    "UTXOState",
    "UTXOTransaction",
    "UTXOOutput",
    "LEDGER_MODELS",
    "get_ledger_model",
]
