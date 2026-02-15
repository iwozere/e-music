// main.js - Entry Point v2.7.5
console.log("MySpotify v2.7.6 - Refactored");

const state = {
    user: null,
    isPlaying: false,
    currentTrack: null,
    currentView: 'home',
    likedTrackIds: new Set(),
    queue: [],
    searchMeta: {
        query: '',
        offset: 0,
        limit: 20,
        isFetching: false,
        hasMore: true
    },
    currentTracksContext: [],
    currentTrackIndex: -1
};

// --- Core Logic ---
const debounce = (func, delay) => {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), delay);
    };
};

const performSearch = async (query, append = false) => {
    if (state.searchMeta.isFetching) return;

    if (!append) {
        state.searchMeta.offset = 0;
        state.searchMeta.hasMore = true;
        state.searchMeta.query = query;
        if (state.currentView !== 'home' || query !== '') state.currentView = 'search';
    }

    state.searchMeta.isFetching = true;
    UI.setLoading(true);

    try {
        const res = await (state.currentView === 'home'
            ? API.getPopular(state.searchMeta.offset, state.searchMeta.limit)
            : API.search(query, state.searchMeta.offset, state.searchMeta.limit));

        const tracks = await res.json();
        state.searchMeta.hasMore = tracks.length === state.searchMeta.limit;

        let title = append ? null : (state.currentView === 'home' ? null : `Results for "${query}"`);
        UI.renderTracks(tracks, title, append);
        state.searchMeta.offset += tracks.length;
        return tracks; // Return tracks for awaiting
    } catch (err) {
        console.error("Search failed:", err);
        return [];
    } finally {
        state.searchMeta.isFetching = false;
        UI.setLoading(false);
    }
};

const debouncedSearch = debounce((q) => performSearch(q), 500);

// --- Initialization ---
const initApp = async () => {
    // Auth Check
    const token = localStorage.getItem('token') || (new URLSearchParams(window.location.hash.substring(1)).get('token'));
    if (token) {
        localStorage.setItem('token', token);
        window.history.replaceState(null, null, window.location.pathname);
        const res = await API.checkAuth(token);
        if (res.ok) {
            state.user = await res.json();
            document.getElementById('auth-modal').style.display = 'none';
        }
    }

    // Google Login
    // For local development, allow viewing home tracks even if not logged in
    console.log('[App] Initializing first view...');
    await loadHome();
    console.log('[App] First view loaded');

    if (!state.user) {
        initGoogleLogin();
    }

    PLAYER.init();
    initEventListeners();
    initInfiniteScroll();
};

const initGoogleLogin = () => {
    const checkGoogle = setInterval(() => {
        if (window.google?.accounts) {
            clearInterval(checkGoogle);
            window.google.accounts.id.initialize({
                client_id: '342747071263-p0a752cdvvj39kuvfsnp2pabrqvb1ivs.apps.googleusercontent.com',
                ux_mode: 'redirect',
                login_uri: `${CONFIG.apiBase}/auth/google/login`
            });
            const btn = document.getElementById(CONFIG.googleBtnId);
            if (btn) window.google.accounts.id.renderButton(btn, { theme: 'outline', size: 'large' });
        }
    }, 100);
};

const initEventListeners = () => {
    // Search
    document.getElementById('main-search')?.addEventListener('input', (e) => debouncedSearch(e.target.value));

    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            if (view === 'search') {
                const searchInput = document.getElementById('main-search');
                const scrollContainer = document.querySelector('.main-content');
                if (scrollContainer) scrollContainer.scrollTop = 0;
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
            } else if (view === 'home') loadHome();
            else if (view === 'liked') loadLikedSongs();
            else if (view === 'library') loadLibrary();
        });
    });

    // Player Buttons
    document.getElementById('btn-play')?.addEventListener('click', () => {
        const audio = document.getElementById('main-audio');
        if (audio.paused) audio.play(); else audio.pause();
        UI.initIcons();
    });
    document.getElementById('btn-next')?.addEventListener('click', playNext);
    document.getElementById('btn-prev')?.addEventListener('click', playPrevious);
};

const initInfiniteScroll = () => {
    const trigger = document.getElementById('infinite-scroll-trigger');
    const scrollContainer = document.querySelector('.main-content');

    if (!trigger || !scrollContainer) {
        console.warn('[InfiniteScroll] Required elements not found:', { trigger: !!trigger, scrollContainer: !!scrollContainer });
        return;
    }

    const observer = new IntersectionObserver((entries) => {
        const entry = entries[0];
        console.log(`[InfiniteScroll] Intersection detected: isIntersecting=${entry.isIntersecting}, ratio=${entry.intersectionRatio.toFixed(2)}`);

        if (entry.isIntersecting && state.searchMeta.hasMore && !state.searchMeta.isFetching) {
            console.log('[InfiniteScroll] Triggering load for view:', state.currentView);
            if (state.searchMeta.query) {
                performSearch(state.searchMeta.query, true);
            } else if (state.currentView === 'home') {
                loadHomeTracks(true);
            }
        }
    }, {
        root: scrollContainer,
        threshold: 0.01, // Slightly above 0 to avoid jitter
        rootMargin: '100px' // Much smaller margin for reliability
    });

    observer.observe(trigger);
    console.log('[InfiniteScroll] Observer attached to trigger');
};

// --- View Loaders ---
window.loadHome = async () => {
    state.currentView = 'home';
    return loadHomeTracks(false);
};

window.loadHomeTracks = async (append = false) => {
    return performSearch('', append);
};

window.loadLikedSongs = async () => {
    state.currentView = 'liked';
    try {
        const res = await API.getLiked();
        if (res.status === 401) {
            UI.showToast("Log in to see your liked songs!");
            document.getElementById('auth-modal').style.display = 'flex';
            // Show empty state for liked songs
            document.getElementById('track-list').innerHTML = `
                <div class="empty-state animate-fade">
                    <i data-lucide="heart" style="width: 48px; height: 48px; color: var(--primary); margin-bottom: 20px;"></i>
                    <h2>Favorites Locked</h2>
                    <p>Log in to keep track of your favorite songs across devices.</p>
                </div>
            `;
            UI.initIcons();
            return;
        }
        if (res.ok) {
            const tracks = await res.json();
            UI.renderTracks(tracks, "Liked Songs");
        }
    } catch (err) {
        console.error("Liked songs load failed:", err);
    }
};

window.loadPlaylist = async (playlistId, name = "Playlist") => {
    state.currentView = 'playlist';
    state.searchMeta.hasMore = false;
    UI.setLoading(true);
    try {
        const res = await API.getPlaylistTracks(playlistId);
        if (res.status === 401) {
            UI.showToast("Log in to see your playlists!");
            document.getElementById('auth-modal').style.display = 'flex';
            return;
        }
        if (res.ok) {
            const tracks = await res.json();
            UI.renderTracks(tracks, name);
        }
    } catch (err) {
        console.error("Playlist load failed:", err);
    } finally {
        UI.setLoading(false);
    }
};

window.loadLibrary = async () => {
    state.currentView = 'library';
    const trackList = document.getElementById('track-list');
    trackList.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const res = await API.getPlaylists();
        if (res.status === 401) {
            trackList.innerHTML = `
                <div class="empty-state animate-fade">
                    <i data-lucide="lock" style="width: 48px; height: 48px; color: var(--primary); margin-bottom: 20px;"></i>
                    <h2>Library Locked</h2>
                    <p>Please log in to view and manage your personal playlists.</p>
                    <button class="btn-primary" onclick="document.getElementById('auth-modal').style.display = 'flex'" style="margin-top: 20px;">
                        Sign In with Google
                    </button>
                </div>
            `;
            UI.initIcons();
            return;
        }

        const playlists = await res.json();
        if (!Array.isArray(playlists) || playlists.length === 0) {
            trackList.innerHTML = `
                <div class="empty-state animate-fade">
                    <i data-lucide="music" style="width: 48px; height: 48px; color: var(--text-muted); margin-bottom: 20px;"></i>
                    <h2>No Playlists Yet</h2>
                    <p>Create your first playlist to start building your library.</p>
                </div>
            `;
            UI.initIcons();
            return;
        }

        trackList.innerHTML = playlists.map(p => `
            <div class="track-card animate-fade" onclick="loadPlaylist('${p.id}', '${p.name.replace(/'/g, "\\'")}')">
                <div class="card-image-container">
                    <div class="track-image" style="background: var(--bg-glass); display: flex; align-items: center; justify-content: center; height: 100%;">
                        <i data-lucide="music" style="width: 48px; height: 48px; color: var(--primary);"></i>
                    </div>
                </div>
                <div class="track-info">
                    <div class="title">${p.name}</div>
                    <div class="artist">Playlist</div>
                </div>
            </div>
        `).join('');
        UI.initIcons();
    } catch (err) {
        console.error("Library load failed:", err);
        trackList.innerHTML = '<p>Error loading library. Please try again later.</p>';
    }
};

window.toggleLike = async (trackId, el) => {
    const isLiked = state.likedTrackIds.has(trackId);
    try {
        const res = await API.toggleLike(trackId, isLiked);
        if (res.status === 401) {
            UI.showToast("Login required to like tracks!");
            document.getElementById('auth-modal').style.display = 'flex';
            return;
        }
        if (res.ok) {
            if (isLiked) state.likedTrackIds.delete(trackId); else state.likedTrackIds.add(trackId);
            if (el) UI.renderTracks(state.currentTracksContext, null, false);
        }
    } catch (err) {
        console.error("Toggle like failed:", err);
    }
};

window.shareItem = (id, type) => {
    const url = `${window.location.origin}/?${type}=${id}`;
    navigator.clipboard.writeText(url);
    UI.showToast("Copied to clipboard!");
};

document.addEventListener('DOMContentLoaded', initApp);
