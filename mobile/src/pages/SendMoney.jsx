import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { useOnlineStatus } from "../hooks/useOnlineStatus";
import { addToQueue } from "../services/syncService";

export default function SendMoney() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isOnline = useOnlineStatus();
  const [recipients, setRecipients] = useState([]);
  const [selectedRecipient, setSelectedRecipient] = useState("");
  const [amount, setAmount] = useState("");
  const [sourceCurrency, setSourceCurrency] = useState("USD");
  const [targetCurrency, setTargetCurrency] = useState("ZAR");
  const [quote, setQuote] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listRecipients(user.id).then(setRecipients).catch(console.error);
  }, [user.id]);

  useEffect(() => {
    if (!selectedRecipient || !amount || parseFloat(amount) <= 0) {
      setQuote(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const q = await api.quoteTransaction({
          user_id: user.id,
          recipient_id: selectedRecipient,
          source_amount: amount,
          source_currency: sourceCurrency,
          target_currency: targetCurrency,
        });
        setQuote(q);
        setError("");
      } catch (err) {
        setError(err.message);
        setQuote(null);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [selectedRecipient, amount, sourceCurrency, targetCurrency, user.id]);

  const handleSend = async () => {
    setLoading(true);
    setError("");
    try {
      if (isOnline) {
        const txn = await api.createTransaction({
          user_id: user.id,
          recipient_id: selectedRecipient,
          source_amount: amount,
          source_currency: sourceCurrency,
          target_currency: targetCurrency,
        });
        navigate(`/transactions/${txn.id}`);
      } else {
        // Offline: queue the transaction locally
        const queuedTxn = {
          id: `offline_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
          user_id: user.id,
          recipient_id: selectedRecipient,
          source_amount: amount,
          source_currency: sourceCurrency,
          target_currency: targetCurrency,
          status: "PENDING",
          created_at: new Date().toISOString(),
          _offline: true,
        };
        addToQueue(queuedTxn);
        navigate("/transactions");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page send-money-page">
      <h2>Send Money</h2>
      {!isOnline && (
        <div className="offline-notice">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="1" y1="1" x2="23" y2="23" />
            <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
            <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
            <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
            <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
            <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
            <line x1="12" y1="20" x2="12.01" y2="20" />
          </svg>
          <span>You're offline. This transaction will be queued and sent when you reconnect.</span>
        </div>
      )}
      <div className="send-form">
        <div className="form-group">
          <label>Recipient</label>
          <select
            value={selectedRecipient}
            onChange={(e) => setSelectedRecipient(e.target.value)}
            required
          >
            <option value="">Select a recipient</option>
            {recipients.map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name} ({r.country})
              </option>
            ))}
          </select>
          {recipients.length === 0 && (
            <p className="form-hint">
              No recipients yet. <a href="/recipients/new">Add one first</a>.
            </p>
          )}
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Amount</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="100.00"
              min="0.01"
              step="0.01"
            />
          </div>
          <div className="form-group">
            <label>From</label>
            <select value={sourceCurrency} onChange={(e) => setSourceCurrency(e.target.value)}>
              <option value="USD">USD</option>
              <option value="ZAR">ZAR</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
        </div>

        <div className="form-group">
          <label>To</label>
          <select value={targetCurrency} onChange={(e) => setTargetCurrency(e.target.value)}>
            <option value="ZAR">ZAR</option>
            <option value="USD">USD</option>
            <option value="GBP">GBP</option>
            <option value="EUR">EUR</option>
            <option value="MWK">MWK</option>
            <option value="ZMW">ZMW</option>
          </select>
        </div>

        {quote && (
          <div className="quote-card">
            <h4>Quote Summary</h4>
            <div className="quote-row">
              <span>You send</span>
              <strong>{quote.source_currency} {quote.source_amount}</strong>
            </div>
            <div className="quote-row">
              <span>Fee</span>
              <strong>{quote.source_currency} {quote.fee_amount}</strong>
            </div>
            <div className="quote-row">
              <span>Total debit</span>
              <strong>{quote.source_currency} {quote.total_debit}</strong>
            </div>
            <div className="quote-row">
              <span>Exchange rate</span>
              <strong>1 {quote.source_currency} = {quote.fx_rate} {quote.target_currency}</strong>
            </div>
            <div className="quote-row highlight">
              <span>Recipient gets</span>
              <strong>{quote.target_currency} {quote.recipient_amount}</strong>
            </div>
          </div>
        )}

        {error && <div className="error-message">{error}</div>}

        <button
          className="btn btn-primary btn-large"
          onClick={handleSend}
          disabled={!quote || loading || !selectedRecipient}
        >
          {loading ? "Processing..." : isOnline ? "Send Money" : "Queue for Sending"}
        </button>
      </div>
    </div>
  );
}
