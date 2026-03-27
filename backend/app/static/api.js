// api.js - Network & Constants
const CONFIG = {
    apiBase: window.location.origin,
    googleBtnId: 'google-login-btn'
};

const apiFetch = async (endpoint, options = {}) => {
    const token = localStorage.getItem('token');
    const headers = { ...options.headers };
    // Only attach auth header when a real token exists — avoids sending 'Bearer null'
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    // Add 30s timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    
    try {
        const response = await fetch(`${CONFIG.apiBase}${endpoint}`, { 
            ...options, 
            headers,
            signal: controller.signal
        });
        clearTimeout(timeoutId);
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

    getSystemConfig: () => fetch(`${CONFIG.apiBase}/system/config`)
};

// Explicit exports for global scope
window.CONFIG = CONFIG;
window.API = API;
