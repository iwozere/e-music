// main.js - Entry Point
console.log("MySpotify v2.9.25");

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
    currentTrackIndex: -1,
    currentPlaylistId: null,
    searchAbortController: null // To cancel previous search requests
};

// --- Core Logic ---
const performSearch = async (query, append = false) => {
    // Cancel any ongoing search request
    if (state.searchAbortController) {
        state.searchAbortController.abort();
    }
    state.searchAbortController = new AbortController();
    const signal = state.searchAbortController.signal;

    if (state.searchMeta.isFetching && append) return;

    if (!append) {
        state.searchMeta.offset = 0;
        state.searchMeta.hasMore = true;
        state.searchMeta.query = query;
        // Only enter "search" mode when there is a query; keep liked/playlist/library/recent
        // intact so headers (Play All, etc.) are not lost to a stale debounced search.
        if (query !== '') {
            state.currentView = 'search';
        }
    }

    state.searchMeta.isFetching = true;
    UI.setLoading(true);

    try {
        let res;
        if (state.currentView === 'home') {
            res = await API.getPopular(state.searchMeta.offset, state.searchMeta.limit, { signal });
        } else if (state.currentView === 'recent') {
            res = await API.getRecent(state.searchMeta.offset, state.searchMeta.limit, { signal });
        } else {
            res = await API.search(query, state.searchMeta.offset, state.searchMeta.limit, { signal });
        }

        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const tracks = await res.json();

        // If query cleared, and we were in search, reload home
        if (query === '' && state.currentView === 'search') {
            state.searchAbortController = null;
            return loadHome();
        }

        // Use server-provided X-Has-More header for pagination accuracy;
        // fall back to tracks.length > 0 for endpoints that don't set it.
        const hasMoreHeader = res.headers.get('X-Has-More');
        state.searchMeta.hasMore = hasMoreHeader !== null ? hasMoreHeader === 'true' : tracks.length > 0;

        let title = append ? null : (state.currentView === 'home' ? null : null);
        UI.renderTracks(tracks, title, append);
        state.searchMeta.offset += tracks.length;
        return tracks;
    } catch (err) {
        if (err.name === 'AbortError') {
            console.log("Search aborted");
        } else {
            console.error("Search failed:", err);
        }
        return [];
    } finally {
        state.searchMeta.isFetching = false;
        UI.setLoading(false);
        state.searchAbortController = null;
    }
};

let searchDebounceTimer = null;
const debouncedSearch = (q) => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        searchDebounceTimer = null;
        performSearch(q);
    }, 500);
};

const cancelPendingSearchDebounce = () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
};

// --- Initialization ---
const initApp = async () => {
    // Auth Check
    const hashPart = window.location.hash.startsWith('#') ? window.location.hash.substring(1) : '';
    const hashParams = new URLSearchParams(hashPart);
    const accessFromHash = hashParams.get('access_token') || hashParams.get('token');
    const refreshFromHash = hashParams.get('refresh_token');
    // Security trade-off: tokens stored in localStorage are accessible to any JS on this
    // origin (XSS risk). For a self-hosted instance this is acceptable; the alternative is
    // HttpOnly cookies with SameSite=Strict. history.replaceState below clears tokens from
    // the URL immediately so they don't persist in browser history.
    const token = localStorage.getItem('token') || accessFromHash;
    if (refreshFromHash) {
        localStorage.setItem('refresh_token', refreshFromHash);
    }
    if (token) {
        localStorage.setItem('token', token);
        window.history.replaceState(null, null, window.location.pathname);
        try {
            const res = await API.checkAuth(token);
            if (res.ok) {
                state.user = await res.json();
                console.log('[Auth] Verfied as:', state.user.username);
                document.getElementById('auth-modal').style.display = 'none';
            } else {
                console.warn('[Auth] Token verification failed:', res.status);
                localStorage.removeItem('token');
                localStorage.removeItem('refresh_token');
            }
        } catch (e) {
            console.error('[Auth] Verification error:', e);
        }
    } else {
        console.log('[Auth] No token found in storage or URL');
    }

    // Google Login
    // For local development, allow viewing home tracks even if not logged in
    try {
        console.log('[App] Loading home tracks...');
        await loadHome();
        console.log('[App] Home tracks loaded.');
    } catch (e) {
        console.error('[App] Failed to load home tracks:', e);
    }

    // Fetch system configuration (Google Client ID, etc.)
    try {
        console.log('[App] Fetching system config...');
        const configRes = await API.getPublicConfig();
        if (configRes.ok) {
            const sysConfig = await configRes.json();
            CONFIG.googleClientId = sysConfig.google_client_id;
            console.log('[App] System config loaded.');
        } else {
            console.warn('[App] Failed to fetch system config:', configRes.status);
        }
    } catch (e) {
        console.error('[App] Error during system config fetch:', e);
    }

    if (!state.user) {
        initGoogleLogin();
    }

    PLAYER.init();
    initEventListeners();
    initInfiniteScroll();
    
    console.log('[App] Initialization complete.');
    UI.setLoading(false);
};

const initGoogleLogin = () => {
    const checkGoogle = setInterval(() => {
        if (window.google?.accounts) {
            clearInterval(checkGoogle);
            window.google.accounts.id.initialize({
                client_id: CONFIG.googleClientId || 'default_client_id',
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
    const searchInput = document.getElementById('main-search');
    const clearBtn = document.getElementById('btn-clear-search');

    searchInput?.addEventListener('input', (e) => {
        const query = e.target.value;
        if (clearBtn) clearBtn.classList.toggle('visible', query.length > 0);
        debouncedSearch(query);
    });

    searchInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const query = e.target.value;
            performSearch(query);
        }
    });

    clearBtn?.addEventListener('click', () => {
        if (searchInput) {
            searchInput.value = '';
            searchInput.focus();
            clearBtn.classList.remove('visible');
            loadHome();
        }
    });

    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            // Clear search on any navigation (and drop stale debounced performSearch)
            cancelPendingSearchDebounce();
            if (state.searchAbortController) {
                state.searchAbortController.abort();
                state.searchAbortController = null;
            }
            if (searchInput) {
                searchInput.value = '';
                if (clearBtn) clearBtn.classList.remove('visible');
            }

            if (view === 'search') {
                const scrollContainer = document.querySelector('.main-content');
                if (scrollContainer) scrollContainer.scrollTop = 0;
                if (searchInput) {
                    searchInput.focus();
                }
                loadHome(); // Alias for search home
            } else if (view === 'home') loadHome();
            else if (view === 'recent') loadRecentSongs();
            else if (view === 'liked') loadLikedSongs();
            else if (view === 'library') loadLibrary();
        });
    });

    // Hum-to-search
    document.getElementById('btn-hum-search')?.addEventListener('click', triggerHumToSearch);

    // Player Buttons
    document.getElementById('btn-play')?.addEventListener('click', async () => {
        const audio = document.getElementById('main-audio');
        if (!audio) return;
        if (audio.paused) {
            // Re-grant if the signed URL has expired (TTL 10 min; user may have been away longer)
            const expired = state.streamUrlExpiresAt && Date.now() >= state.streamUrlExpiresAt;
            if (expired && state.currentTrack) {
                const t = state.currentTrack;
                await playTrack(t.id, t.title, t.artist, t.thumbnail);
                return;
            }
            try {
                await audio.play();
            } catch (_) {
                // play() rejected (e.g. URL expired mid-session) — re-grant and restart
                if (state.currentTrack) {
                    const t = state.currentTrack;
                    await playTrack(t.id, t.title, t.artist, t.thumbnail);
                    return;
                }
            }
        } else {
            audio.pause();
        }
        UI.initIcons();
    });
    document.getElementById('btn-next')?.addEventListener('click', playNext);
    document.getElementById('btn-prev')?.addEventListener('click', playPrevious);
    document.getElementById('btn-ai-shuffle')?.addEventListener('click', triggerAiShuffle);
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
        if (entry.isIntersecting && state.searchMeta.hasMore && !state.searchMeta.isFetching) {
            console.log('[InfiniteScroll] Triggering loadMore');
            loadMore();
        }
    }, {
        root: scrollContainer,
        threshold: 0.01,
        rootMargin: '100px'
    });

    observer.observe(trigger);
    console.log('[InfiniteScroll] Observer attached to trigger');
};

// --- View Loaders ---
window.loadHome = async () => {
    state.currentView = 'home';
    state.currentPlaylistId = null;
    return loadHomeTracks(false);
};

window.loadRecentSongs = async () => {
    state.currentView = 'recent';
    state.currentPlaylistId = null;
    return loadHomeTracks(false);
};

window.loadMore = async () => {
    // Liked / playlist / library load full lists in one shot — do not paginate or the
    // append path calls renderTracks(..., null, true) which hides the view header (Play All, etc.).
    const paginatedViews = ['home', 'recent', 'search'];
    if (!paginatedViews.includes(state.currentView)) {
        return;
    }
    if (state.searchMeta.query) {
        return performSearch(state.searchMeta.query, true);
    } else {
        return loadHomeTracks(true);
    }
};

window.loadHomeTracks = async (append = false) => {
    return performSearch('', append);
};

window.loadLikedSongs = async () => {
    state.currentView = 'liked';
    state.currentPlaylistId = null;
    state.searchMeta.hasMore = false;
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
            state.currentView = 'liked';
            UI.renderTracks(tracks, "Liked Songs");
        }
    } catch (err) {
        console.error("Liked songs load failed:", err);
    }
};

window.loadPlaylist = async (playlistId, name = "Playlist") => {
    cancelPendingSearchDebounce();
    if (state.searchAbortController) {
        state.searchAbortController.abort();
        state.searchAbortController = null;
    }
    state.currentView = 'playlist';
    state.currentPlaylistId = playlistId;
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
            state.currentView = 'playlist';
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
    state.currentPlaylistId = null;
    const trackList = document.getElementById('track-list');
    const viewTitle = document.querySelector('#content-view h1');

    if (viewTitle) {
        viewTitle.style.display = 'block';
        viewTitle.innerText = "Your Library";
    }

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
                    <button class="btn-primary" onclick="createNewPlaylist()" style="margin-top: 20px; width: auto; padding: 12px 24px;">
                        Create Playlist
                    </button>
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
    // Guard: show login modal immediately without a network round-trip
    if (!state.user) {
        UI.showToast("Login required to like tracks!");
        document.getElementById('auth-modal').style.display = 'flex';
        return;
    }
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
            if (el) {
                let headerTitle = null;
                if (state.currentView === 'liked') headerTitle = 'Liked Songs';
                else if (state.currentView === 'playlist') {
                    const nameSpan = document.querySelector('#content-view h1 > span');
                    headerTitle = nameSpan ? nameSpan.textContent.trim() : null;
                }
                UI.renderTracks(state.currentTracksContext, headerTitle, false);
            }
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

window.createNewPlaylist = async () => {
    if (!state.user) {
        UI.showToast("Please login to create playlists!");
        document.getElementById('auth-modal').style.display = 'flex';
        return;
    }

    const name = prompt("Enter playlist name:");
    if (!name || name.trim() === "") return;

    try {
        const res = await API.createPlaylist(name);
        if (res.ok) {
            UI.showToast(`Playlist "${name}" created!`);
            if (state.currentView === 'library') {
                loadLibrary();
            }
        } else {
            const err = await res.json();
            UI.showToast(`Error: ${err.detail || 'Failed to create playlist'}`);
        }
    } catch (err) {
        console.error("Create playlist failed:", err);
        UI.showToast("Connection error. Try again.");
    }
};

window.removeFromPlaylist = async (trackId) => {
    if (!state.currentPlaylistId) return;

    try {
        const res = await API.removeTrackFromPlaylist(state.currentPlaylistId, trackId);
        if (res.ok) {
            UI.showToast("Track removed from playlist");
            // Reload the current playlist view
            const viewTitle = document.querySelector('#content-view h1');
            const playlistName = viewTitle ? viewTitle.innerText.split(' Play All')[0].trim() : "Playlist";
            loadPlaylist(state.currentPlaylistId, playlistName);
        } else {
            const err = await res.json();
            UI.showToast(`Error: ${err.detail || 'Failed to remove track'}`);
        }
    } catch (err) {
        console.error("Remove track failed:", err);
        UI.showToast("Connection error. Try again.");
    }
};

window.triggerAiShuffle = async () => {
    if (!state.user) {
        UI.showToast("Log in to use AI Shuffle");
        document.getElementById('auth-modal').style.display = 'flex';
        return;
    }
    const contextIds = (state.currentTracksContext || []).map(t => trackPlaybackId(t)).filter(Boolean);
    if (contextIds.length === 0 && !state.currentTrack) {
        UI.showToast("Play something first to use AI Shuffle");
        return;
    }
    // Include current track if context is empty (single-track scenario)
    const ids = contextIds.length > 0 ? contextIds : [trackPlaybackId(state.currentTrack)].filter(Boolean);

    UI.showToast("AI is curating your next tracks...");
    try {
        const res = await API.aiShuffle(ids);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            UI.showToast(err.detail || "AI shuffle failed, try again.");
            return;
        }
        const tracks = await res.json();
        if (!tracks.length) {
            UI.showToast("AI returned no suggestions — try again.");
            return;
        }
        tracks.forEach(t => state.queue.push(t));
        UI.renderQueue();
        // Start immediately when called at end-of-context: audio.ended is true
        // but state.isPlaying hasn't been reset yet. Also handle the paused/idle case.
        const audio = document.getElementById('main-audio');
        const audioIdle = !audio || audio.paused || audio.ended;
        if (!state.isPlaying || audioIdle) {
            const first = state.queue.shift();
            UI.renderQueue();
            playTrack(trackPlaybackId(first), first.title, first.artist, first.thumbnail);
        } else {
            UI.showToast(`Added ${tracks.length} tracks to queue`);
        }
    } catch (err) {
        console.error("AI shuffle error:", err);
        UI.showToast("AI shuffle failed — check your connection.");
    }
};

window.triggerHumToSearch = async () => {
    if (!state.user) {
        UI.showToast("Log in to use hum-to-search");
        document.getElementById('auth-modal').style.display = 'flex';
        return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
        UI.showToast("Microphone not supported in this browser");
        return;
    }

    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch {
        UI.showToast("Microphone access denied");
        return;
    }

    const modal = document.getElementById('hum-modal');
    const recordingState = document.getElementById('hum-recording-state');
    const identifyingState = document.getElementById('hum-identifying-state');
    const countdownEl = document.getElementById('hum-countdown');

    // Reset to recording state
    recordingState.style.display = 'block';
    identifyingState.style.display = 'none';
    const DURATION = 10;
    countdownEl.textContent = DURATION;
    modal.style.display = 'flex';

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];
    recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };

    let cancelled = false;
    let ticker = null;

    const stopAll = () => {
        clearInterval(ticker);
        recorder.state !== 'inactive' && recorder.stop();
        stream.getTracks().forEach(t => t.stop());
    };

    document.getElementById('btn-hum-cancel').onclick = () => {
        cancelled = true;
        stopAll();
        modal.style.display = 'none';
    };

    let remaining = DURATION;
    ticker = setInterval(() => {
        remaining--;
        countdownEl.textContent = remaining;
        if (remaining <= 0) stopAll();
    }, 1000);

    recorder.start();

    recorder.onstop = async () => {
        clearInterval(ticker);
        if (cancelled) return;

        recordingState.style.display = 'none';
        identifyingState.style.display = 'block';

        const blob = new Blob(chunks, { type: mimeType });
        const formData = new FormData();
        formData.append('audio', blob, 'hum.webm');

        try {
            const res = await API.identify(formData);
            modal.style.display = 'none';

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                // error_handlers.py shape: {message, detail} — detail is null for string errors,
                // an object for structured ones (e.g. low_confidence).
                const msg = (err.detail && err.detail.message)
                    || err.message
                    || "Could not identify the melody";
                UI.showToast(msg);
                return;
            }

            const data = await res.json();
            const query = `${data.artist} - ${data.title}`;
            const searchInput = document.getElementById('main-search');
            const clearBtn = document.getElementById('btn-clear-search');
            searchInput.value = query;
            clearBtn.classList.add('visible');
            performSearch(query);
        } catch (err) {
            modal.style.display = 'none';
            if (err.name === 'AbortError') {
                UI.showToast("Request timed out — check your connection");
            } else {
                UI.showToast("Connection error — try again");
            }
            console.error("Hum-to-search error:", err);
        }
    };
};

document.addEventListener('DOMContentLoaded', initApp);
