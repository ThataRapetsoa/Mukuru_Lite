import { useState, useEffect } from "react";
import { api } from "../api/client";

const CURRENCIES = ["USD", "ZAR", "GBP", "EUR", "MWK", "ZMW", "BWP"];

export default function CurrencyCalculator() {
  const [amount, setAmount] = useState("100");
  const [from, setFrom] = useState("USD");
  const [to, setTo] = useState("ZAR");
  const [result, setResult] = useState(null);
  const [rate, setRate] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!amount || parseFloat(amount) <= 0) {
      setResult(null);
      setRate(null);
      return;
    }
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const fxData = await api.getFxRate(from, to);
        const converted = (parseFloat(amount) * parseFloat(fxData.rate)).toFixed(2);
        setResult(converted);
        setRate(fxData.rate);
      } catch (err) {
        setResult(null);
        setRate(null);
      } finally {
        setLoading(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [amount, from, to]);

  const swap = () => {
    setFrom(to);
    setTo(from);
  };

  return (
    <div className="calculator-card">
      <div className="calculator-header">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="12" y1="1" x2="12" y2="23" />
          <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
        <h3>Currency Calculator</h3>
      </div>
      <div className="calculator-body">
        <div className="calc-row">
          <div className="calc-field">
            <label>Amount</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="100"
              min="0"
              step="0.01"
            />
          </div>
        </div>
        <div className="calc-row">
          <div className="calc-field">
            <label>From</label>
            <select value={from} onChange={(e) => setFrom(e.target.value)}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <button className="swap-btn" onClick={swap} aria-label="Swap currencies">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="17 1 21 5 17 9" />
              <path d="M3 11V9a4 4 0 0 1 4-4h14" />
              <polyline points="7 23 3 19 7 15" />
              <path d="M21 13v2a4 4 0 0 1-4 4H3" />
            </svg>
          </button>
          <div className="calc-field">
            <label>To</label>
            <select value={to} onChange={(e) => setTo(e.target.value)}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        </div>
        {loading && <p className="calc-loading">Getting rate...</p>}
        {result && !loading && (
          <div className="calc-result">
            <div className="calc-result-amount">
              {to} {result}
            </div>
            <div className="calc-result-rate">
              1 {from} = {rate} {to}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
