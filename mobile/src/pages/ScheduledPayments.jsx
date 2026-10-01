import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

function localDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initialScheduleDate() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return localDateValue(date);
}

function minimumScheduleDate() {
  const now = new Date();
  if (now.getHours() >= 9) now.setDate(now.getDate() + 1);
  return localDateValue(now);
}

function formatScheduleDate(value) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const FREQUENCIES = [
  { value: "ONCE", label: "Once" },
  { value: "WEEKLY", label: "Weekly" },
  { value: "MONTHLY", label: "Monthly" },
];

export default function ScheduledPayments() {
  const { user } = useAuth();
  const [recipients, setRecipients] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [recipientId, setRecipientId] = useState("");
  const [amount, setAmount] = useState("");
  const [sourceCurrency, setSourceCurrency] = useState("USD");
  const [targetCurrency, setTargetCurrency] = useState("ZAR");
  const [frequency, setFrequency] = useState("ONCE");
  const [runDate, setRunDate] = useState(initialScheduleDate);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [recipientData, scheduleData] = await Promise.all([
        api.listRecipients(user.id),
        api.listSchedules(user.id),
      ]);
      setRecipients(recipientData);
      setSchedules(scheduleData);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [user.id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const scheduledAt = new Date(`${runDate}T09:00:00`).toISOString();
      await api.createSchedule({
        user_id: user.id,
        recipient_id: recipientId,
        source_amount: amount,
        source_currency: sourceCurrency,
        target_currency: targetCurrency,
        frequency,
        next_run_at: scheduledAt,
      });
      setAmount("");
      await loadData();
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSaving(false);
    }
  };

  const cancelSchedule = async (scheduleId) => {
    setError("");
    try {
      await api.deleteSchedule(scheduleId);
      setSchedules((current) => current.filter((schedule) => schedule.id !== scheduleId));
    } catch (cancelError) {
      setError(cancelError.message);
    }
  };

  const upcomingSchedules = schedules.filter((schedule) => schedule.active);

  return (
    <div className="page scheduled-payments-page">
      <h2>Scheduled Payments</h2>
      <p className="schedule-intro">Choose when your next transfer should be sent.</p>

      <form className="form schedule-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="schedule-recipient">Recipient</label>
          <select
            id="schedule-recipient"
            value={recipientId}
            onChange={(event) => setRecipientId(event.target.value)}
            required
          >
            <option value="">Select a recipient</option>
            {recipients.map((recipient) => (
              <option key={recipient.id} value={recipient.id}>
                {recipient.full_name} ({recipient.country})
              </option>
            ))}
          </select>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="schedule-amount">Amount</label>
            <input
              id="schedule-amount"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="50.00"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="schedule-frequency">Frequency</label>
            <select
              id="schedule-frequency"
              value={frequency}
              onChange={(event) => setFrequency(event.target.value)}
            >
              {FREQUENCIES.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="schedule-source-currency">From</label>
            <select
              id="schedule-source-currency"
              value={sourceCurrency}
              onChange={(event) => setSourceCurrency(event.target.value)}
            >
              <option value="USD">USD</option>
              <option value="ZAR">ZAR</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="schedule-target-currency">To</label>
            <select
              id="schedule-target-currency"
              value={targetCurrency}
              onChange={(event) => setTargetCurrency(event.target.value)}
            >
              <option value="ZAR">ZAR</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
              <option value="MWK">MWK</option>
              <option value="ZMW">ZMW</option>
            </select>
          </div>
        </div>

        <div className="form-group">
          <label htmlFor="schedule-date">First payment date</label>
          <input
            id="schedule-date"
            type="date"
            min={minimumScheduleDate()}
            value={runDate}
            onChange={(event) => setRunDate(event.target.value)}
            required
          />
          <p className="form-hint">Payments run at 9:00 AM in your device's time zone.</p>
        </div>

        {error && <div className="error-message" role="alert">{error}</div>}
        <button
          type="submit"
          className="btn btn-primary btn-large"
          disabled={saving || recipients.length === 0}
        >
          {saving ? "Scheduling..." : "Schedule Payment"}
        </button>
        {recipients.length === 0 && !loading && (
          <p className="form-hint">Add a recipient before scheduling a payment.</p>
        )}
      </form>

      <section className="schedule-section" aria-labelledby="upcoming-schedules-title">
        <h3 id="upcoming-schedules-title">Upcoming</h3>
        {loading ? (
          <p className="loading-text">Loading...</p>
        ) : upcomingSchedules.length === 0 ? (
          <div className="empty-state"><p>No upcoming payments</p></div>
        ) : (
          <div className="schedule-list">
            {upcomingSchedules.map((schedule) => {
              const recipient = recipients.find((item) => item.id === schedule.recipient_id);
              const cadence = FREQUENCIES.find((item) => item.value === schedule.frequency)?.label;
              return (
                <article className="schedule-item" key={schedule.id}>
                  <div className="schedule-item-details">
                    <strong>{recipient?.full_name || "Recipient"}</strong>
                    <span>{cadence} · {formatScheduleDate(schedule.next_run_at)}</span>
                    <span>{schedule.source_currency} {schedule.source_amount} → {schedule.target_currency}</span>
                  </div>
                  <button
                    type="button"
                    className="schedule-cancel"
                    aria-label={`Cancel payment to ${recipient?.full_name || "recipient"}`}
                    onClick={() => cancelSchedule(schedule.id)}
                  >
                    Cancel
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}