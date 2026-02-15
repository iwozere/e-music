// api.js - Network & Constants v2.7.5
const CONFIG = {
    apiBase: window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
        ? window.location.origin
        : 'https://api.e-music.win',
    googleBtnId: 'google-login-btn'
};

const apiFetch = async (endpoint, options = {}) => {
    const token = localStorage.getItem('token');
    const headers = {
        'Authorization': `Bearer ${token}`,
        ...options.headers
    };
    return fetch(`${CONFIG.apiBase}${endpoint}`, { ...options, headers });
};

const API = {
    search: (query, offset, limit) =>
        apiFetch(`/search?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`),

    getPopular: (offset, limit) =>
        apiFetch(`/tracks/popular?offset=${offset}&limit=${limit}`),

    getLiked: () => apiFetch('/tracks/liked'),

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
    })
};

// Explicit exports for global scope
window.CONFIG = CONFIG;
window.API = API;
