export async function api(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
        throw new Error(payload.message || '请求失败');
    }
    return payload;
}
