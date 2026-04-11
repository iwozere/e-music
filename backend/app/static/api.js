// api.js - Network & Constants
const CONFIG = {
    apiBase: `${window.location.origin}/api/v1`,
    googleBtnId: 'google-login-btn'
};

/**
 * Id for stream/grant, likes, playlists, queue. Prefer internal UUID so the backend
 * resolves the DB row by primary key. Raw YouTube search rows only have videoId (11 chars).
 */
function trackPlaybackId(track) {
    if (!track) return '';
    const raw = track.id;
    const rid = track.remote_id;
    if (track.source_type === 'local' && raw) return String(raw);
    if (typeof raw === 'string' && raw.length === 36 && raw.split('-').length === 5) {
        return raw;
    }
    return raw || rid || '';
}

const tryRefreshTokens = async () => {
    const refresh = localStorage.getItem('refresh_token');
    if (!refresh) return false;
    const res = await fetch(`${CONFIG.apiBase}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem('token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return true;
};

const apiFetch = async (endpoint, options = {}, retried = false) => {
    const token = localStorage.getItem('token');
    const headers = { ...options.headers };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        let response = await fetch(`${CONFIG.apiBase}${endpoint}`, {
            ...options,
            headers,
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        if (!retried && response.status === 401 && localStorage.getItem('refresh_token')) {
            if (await tryRefreshTokens()) {
                return apiFetch(endpoint, options, true);
            }
        }
        return response;
    } catch (e) {
        clearTimeout(timeoutId);
        throw e;
    }
};

const API = {
    search: (query, offset, limit, options) =>
        apiFetch(`/tracks/search?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`, options),

    getPopular: (offset, limit, options) =>
        apiFetch(`/tracks/popular?offset=${offset}&limit=${limit}`, options),

    getLiked: () => apiFetch('/tracks/liked'),

    getRecent: (offset, limit, options) =>
        apiFetch(`/tracks/recent?offset=${offset}&limit=${limit}`, options),

    toggleLike: (trackId, isLiked) =>
        apiFetch(`/tracks/${trackId}/like?is_liked=${!isLiked}`, { method: 'POST' }),

    getPlaylists: () => apiFetch('/playlists'),

    getPlaylistTracks: (playlistId) => apiFetch(`/playlists/${playlistId}/tracks`),

    addTrackToPlaylist: (playlistId, trackId) => {
        const formData = new URLSearchParams();
        formData.append('track_id', trackId);
        return apiFetch(`/playlists/${playlistId}/tracks`, {
            method: 'POST',
            body: formData,
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        });
    },

    removeTrackFromPlaylist: (playlistId, trackId) =>
        apiFetch(`/playlists/${playlistId}/tracks/${trackId}`, { method: 'DELETE' }),

    deletePlaylist: (playlistId) =>
        apiFetch(`/playlists/${playlistId}`, { method: 'DELETE' }),

    createPlaylist: (name) => {
        const formData = new URLSearchParams();
        formData.append('name', name);
        return apiFetch('/playlists', {
            method: 'POST',
            body: formData,
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        });
    },

    checkAuth: (token) => fetch(`${CONFIG.apiBase}/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
    }),

    getPublicConfig: () => fetch(`${CONFIG.apiBase}/config`)
};

// Explicit exports for global scope
window.CONFIG = CONFIG;
window.API = API;
