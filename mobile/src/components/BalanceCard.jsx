import { useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";

export default function BalanceCard({ balances, onDeposit }) {
  const { user } = useAuth();
  const [showDeposit, setShowDeposit] = useState(false);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleDeposit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.depositBalance({
        user_id: user.id,
        currency,
        amount,
        idempotency_key: `deposit_${Date.now()}`,
      });
      setShowDeposit(false);
      setAmount("");
      onDeposit();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (balances.length === 0) {
    return (
      <div className="balance-card empty">
        <div className="balance-header">
          <h3>Your Balance</h3>
        </div>
        <p className="balance-empty">No funds yet</p>
        <button className="btn btn-primary" onClick={() => setShowDeposit(true)}>
          Add Funds
        </button>
        {showDeposit && (
          <DepositModal
            amount={amount}
            setAmount={setAmount}
            currency={currency}
            setCurrency={setCurrency}
            loading={loading}
            error={error}
            onSubmit={handleDeposit}
            onClose={() => setShowDeposit(false)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="balance-card">
      <div className="balance-header">
        <h3>Your Balance</h3>
        <button className="btn btn-small" onClick={() => setShowDeposit(true)}>
          + Add Funds
        </button>
      </div>
      <div className="balance-list">
        {balances.map((b) => (
          <div key={b.currency} className="balance-item">
            <span className="balance-currency">{b.currency}</span>
            <span className="balance-amount">{b.available_balance}</span>
          </div>
        ))}
      </div>
      {showDeposit && (
        <DepositModal
          amount={amount}
          setAmount={setAmount}
          currency={currency}
          setCurrency={setCurrency}
          loading={loading}
          error={error}
          onSubmit={handleDeposit}
          onClose={() => setShowDeposit(false)}
        />
      )}
    </div>
  );
}

function DepositModal({ amount, setAmount, currency, setCurrency, loading, error, onSubmit, onClose }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Add Funds</h3>
        <p className="modal-subtitle">Add demo funds to your wallet</p>
        <form onSubmit={onSubmit}>
          <div className="form-group">
            <label>Amount</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="100.00"
              min="0.01"
              step="0.01"
              required
            />
          </div>
          <div className="form-group">
            <label>Currency</label>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="USD">USD</option>
              <option value="ZAR">ZAR</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
          {error && <div className="error-message">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? "Adding..." : "Add Funds"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
