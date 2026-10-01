import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

export default function SendMoney() {
  const { user } = useAuth();
  const navigate = useNavigate();
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
      const txn = await api.createTransaction({
        user_id: user.id,
        recipient_id: selectedRecipient,
        source_amount: amount,
        source_currency: sourceCurrency,
        target_currency: targetCurrency,
      });
      navigate(`/transactions/${txn.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page send-money-page">
      <h2>Send Money</h2>
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
          {loading ? "Processing..." : "Send Money"}
        </button>
      </div>
    </div>
  );
}
