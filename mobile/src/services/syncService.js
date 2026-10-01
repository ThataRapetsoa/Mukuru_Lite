import { api } from "../api/client";

const QUEUE_KEY = "mukuru_offline_queue";

export function getQueue() {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY)) || [];
  } catch {
    return [];
  }
}

export function addToQueue(transaction) {
  const queue = getQueue();
  queue.push({
    ...transaction,
    _queued_at: new Date().toISOString(),
  });
  localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
}

export function clearQueue() {
  localStorage.removeItem(QUEUE_KEY);
}

export async function syncQueue(onProgress) {
  const queue = getQueue();
  if (queue.length === 0) return { synced: 0, failed: 0 };

  let synced = 0;
  let failed = 0;
  const remaining = [];

  for (const item of queue) {
    try {
      // Transition the transaction to IN_TRANSIT
      await api.updateTransactionStatus(item.id, {
        status: "IN_TRANSIT",
        note: "Synced after coming back online",
      });
      synced++;
      onProgress?.({ synced, failed, total: queue.length, current: item });
    } catch (err) {
      // If it fails, keep it in the queue for next time
      remaining.push(item);
      failed++;
      onProgress?.({ synced, failed, total: queue.length, current: item, error: err });
    }
  }

  localStorage.setItem(QUEUE_KEY, JSON.stringify(remaining));
  return { synced, failed, remaining: remaining.length };
}

export function isQueued(transactionId) {
  return getQueue().some((item) => item.id === transactionId);
}
