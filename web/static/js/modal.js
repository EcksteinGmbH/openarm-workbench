import { state } from './store.js';

export function showModal(title, body, onConfirm) {
    state.pendingModalAction = onConfirm;
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').textContent = body;
    document.getElementById('confirmModal').classList.remove('hidden');
}

export function closeModal() {
    state.pendingModalAction = null;
    document.getElementById('confirmModal').classList.add('hidden');
}
