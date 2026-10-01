const BASE_URL = "/api";

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  // Users
  createUser: (data) => request("/users", { method: "POST", body: JSON.stringify(data) }),
  getUser: (userId) => request(`/users/${userId}`),

  // Recipients
  createRecipient: (data) => request("/recipients", { method: "POST", body: JSON.stringify(data) }),
  listRecipients: (userId) => request(`/recipients?user_id=${userId}`),
  getRecipient: (id) => request(`/recipients/${id}`),

  // Transactions
  quoteTransaction: (data) => request("/transactions/quote", { method: "POST", body: JSON.stringify(data) }),
  createTransaction: (data) => request("/transactions", { method: "POST", body: JSON.stringify(data) }),
  listTransactions: (userId) => request(`/transactions?user_id=${userId}`),
  getTransaction: (id) => request(`/transactions/${id}`),
  updateTransactionStatus: (id, data) => request(`/transactions/${id}/status`, { method: "PATCH", body: JSON.stringify(data) }),
  cancelTransaction: (id) => request(`/transactions/${id}/cancel`, { method: "POST" }),

  // Balances
  getBalances: (userId) => request(`/balances?user_id=${userId}`),
  depositBalance: (data) => request("/balances/deposit", { method: "POST", body: JSON.stringify(data) }),

  // FX
  getFxRate: (from, to) => request(`/fx/rate?from_currency=${from}&to_currency=${to}`),

  // Notifications
  listNotifications: (userId) => request(`/notifications?user_id=${userId}`),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: "PATCH" }),

  // Scheduled Payments
  createSchedule: (data) => request("/scheduled-payments", { method: "POST", body: JSON.stringify(data) }),
  listSchedules: (userId) => request(`/scheduled-payments?user_id=${userId}`),
  updateSchedule: (id, data) => request(`/scheduled-payments/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteSchedule: (id) => request(`/scheduled-payments/${id}`, { method: "DELETE" }),
};
