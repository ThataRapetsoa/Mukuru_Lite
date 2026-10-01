import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

export default function AddRecipient() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    full_name: "",
    phone_number: "",
    country: "",
    payout_method: "mobile_money",
    payout_details: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.createRecipient({
        ...form,
        user_id: user.id,
      });
      navigate("/recipients");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page add-recipient-page">
      <h2>Add Recipient</h2>
      <form onSubmit={handleSubmit} className="form">
        <div className="form-group">
          <label htmlFor="full_name">Full Name</label>
          <input
            id="full_name"
            name="full_name"
            type="text"
            value={form.full_name}
            onChange={handleChange}
            placeholder="Tariro Moyo"
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="phone_number">Phone Number</label>
          <input
            id="phone_number"
            name="phone_number"
            type="tel"
            value={form.phone_number}
            onChange={handleChange}
            placeholder="+263771234567"
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="country">Country</label>
          <select
            id="country"
            name="country"
            value={form.country}
            onChange={handleChange}
            required
          >
            <option value="">Select country</option>
            <option value="ZW">Zimbabwe</option>
            <option value="ZA">South Africa</option>
            <option value="MW">Malawi</option>
            <option value="ZM">Zambia</option>
            <option value="MZ">Mozambique</option>
            <option value="BW">Botswana</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="payout_method">Payout Method</label>
          <select
            id="payout_method"
            name="payout_method"
            value={form.payout_method}
            onChange={handleChange}
            required
          >
            <option value="mobile_money">Mobile Money</option>
            <option value="bank_transfer">Bank Transfer</option>
            <option value="cash_collection">Cash Collection</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="payout_details">Payout Details (optional)</label>
          <input
            id="payout_details"
            name="payout_details"
            type="text"
            value={form.payout_details}
            onChange={handleChange}
            placeholder="EcoCash 0771234567"
          />
        </div>
        {error && <div className="error-message">{error}</div>}
        <button type="submit" className="btn btn-primary btn-large" disabled={loading}>
          {loading ? "Adding..." : "Add Recipient"}
        </button>
      </form>
    </div>
  );
}
