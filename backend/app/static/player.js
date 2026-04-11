// player.js - Audio Logic & Media Session
const PLAYER = {
    init: () => {
        const audio = document.getElementById('main-audio');
        if (!audio) return;

        audio.addEventListener('error', () => {
            const err = audio.error;
            console.warn(
                '[Player] <audio> error:',
                err ? `code=${err.code} ${err.message || ''}` : 'unknown',
                'src=',
                audio.currentSrc || audio.src,
                'networkState=',
                audio.networkState,
            );
        });

        audio.addEventListener('timeupdate', () => {
            const d = audio.duration;
            const hasFiniteDuration = Number.isFinite(d) && d > 0;
            // Chunked streams (e.g. YouTube proxy) often have no Content-Length → duration is Infinity/NaN
            const percent = hasFiniteDuration ? (audio.currentTime / d) * 100 : 0;
            const seekFill = document.getElementById('seek-fill');
            const currentTimeEl = document.getElementById('current-time');
            const totalTimeEl = document.getElementById('total-time');

            if (seekFill) seekFill.style.width = `${hasFiniteDuration ? percent : 0}%`;
            if (currentTimeEl) currentTimeEl.innerText = PLAYER.formatTime(audio.currentTime);
            if (totalTimeEl) totalTimeEl.innerText = PLAYER.formatTime(d);
        });

        audio.addEventListener('ended', () => {
            console.log("[Player] Track ended, jumping to next.");
            playNext();
        });

        // Volume Control Init
        audio.volume = 0.8;

        // Seeker Interaction
        const seekBar = document.getElementById('seek-bar');
        if (seekBar) {
            seekBar.addEventListener('click', (e) => {
                const rect = seekBar.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const percent = x / rect.width;
                const d = audio.duration;
                if (Number.isFinite(d) && d > 0) {
                    audio.currentTime = percent * d;
                }
            });
        }

        // Volume Interaction
        const volumeSlider = document.getElementById('volume-slider');
        if (volumeSlider) {
            volumeSlider.addEventListener('click', (e) => {
                const rect = volumeSlider.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const percent = Math.max(0, Math.min(1, x / rect.width));
                audio.volume = percent;

                const volumeFill = document.getElementById('volume-fill');
                if (volumeFill) volumeFill.style.width = `${percent * 100}%`;
            });
        }
    },

    formatTime: (seconds) => {
        // Infinity/NaN: streamed audio without known length (no Content-Length); not "invalid" time
        if (!Number.isFinite(seconds) || seconds < 0) return '--:--';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    },

    updateMediaSession: (track) => {
        if (!('mediaSession' in navigator)) return;
        navigator.mediaSession.metadata = new MediaMetadata({
            title: track.title,
            artist: track.artist,
            artwork: [{ src: track.thumbnail, sizes: '512x512', type: 'image/png' }]
        });
    }
};

window.PLAYER = PLAYER;

/** After a failed <audio> load, fetch the same signed URL once to read FastAPI JSON `detail` (503). */
async function fetchStreamErrorDetail(url) {
    try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 12000);
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) {
            const j = await r.json().catch(() => null);
            if (!j || j.detail == null) return null;
            if (typeof j.detail === 'string') return j.detail;
            if (Array.isArray(j.detail)) {
                return j.detail.map((e) => e.msg || JSON.stringify(e)).join('; ');
            }
            return String(j.detail);
        }
    } catch (_) { /* network / abort */ }
    return null;
}

/** Grant URLs must be https when the app runs on https (mixed content blocks <audio src=http>). */
function coerceStreamUrlToPageHttps(url) {
    if (!url || typeof url !== 'string' || window.location.protocol !== 'https:') return url;
    try {
        const u = new URL(url, window.location.href);
        if (u.protocol === 'http:') {
            u.protocol = 'https:';
            return u.href;
        }
    } catch (_) { /* ignore */ }
    return url;
}

window.playTrack = async (trackId, title, artist, thumbnail) => {
    state.currentTrack = { id: trackId, title, artist, thumbnail };
    state.isPlaying = true;

    const playerMetadata = document.getElementById('player-metadata');
    if (playerMetadata) playerMetadata.style.visibility = 'visible';

    const audio = document.getElementById('main-audio');
    const playBtn = document.getElementById('btn-play');

    state.currentTrackIndex = state.currentTracksContext.findIndex(
        (t) => trackPlaybackId(t) === trackId
    );

    document.getElementById('player-title').innerText = title || "Unknown Title";
    document.getElementById('player-artist').innerText = artist || "Unknown Artist";

    const validThumb = (thumbnail && thumbnail !== 'null') ? thumbnail : 'https://images.unsplash.com/photo-1493225255756-d9584f8606e9?w=300&q=80';
    document.getElementById('player-img').src = validThumb;

    // Like Button Sync
    const likeBtn = document.getElementById('btn-like');
    if (likeBtn) {
        const icon = likeBtn.querySelector('i, svg');
        if (state.likedTrackIds.has(trackId)) {
            likeBtn.classList.add('active');
            if (icon) icon.setAttribute('fill', '#ef4444');
        } else {
            likeBtn.classList.remove('active');
            if (icon) icon.removeAttribute('fill');
        }
    }

    if (audio) {
        const token = localStorage.getItem('token');
        if (!token) {
            if (typeof UI !== 'undefined' && UI.showToast) {
                UI.showToast('Log in to play music');
            }
            state.isPlaying = false;
            UI.initIcons();
            return;
        }
        const grantRes = await fetch(`${CONFIG.apiBase}/tracks/stream/grant`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ track_id: trackId }),
        });
        if (grantRes.status === 401) {
            localStorage.removeItem('token');
            localStorage.removeItem('refresh_token');
            if (typeof UI !== 'undefined' && UI.showToast) {
                UI.showToast('Session expired; please log in again');
            }
            state.isPlaying = false;
            UI.initIcons();
            return;
        }
        if (!grantRes.ok) {
            console.warn('[Player] stream/grant failed:', grantRes.status);
            state.isPlaying = false;
            UI.initIcons();
            return;
        }
        const grantJson = await grantRes.json();
        let streamUrl = grantJson.stream_url;
        if (!streamUrl) {
            console.warn('[Player] stream/grant returned no stream_url');
            if (typeof UI !== 'undefined' && UI.showToast) UI.showToast('Could not get playback URL');
            state.isPlaying = false;
            UI.initIcons();
            return;
        }
        streamUrl = coerceStreamUrlToPageHttps(streamUrl);
        console.log("[Player] Setting audio source (signed URL)");
        audio.src = streamUrl;
        try {
            await audio.play();
            if (playBtn) playBtn.innerHTML = '<i data-lucide="pause"></i>';
            PLAYER.updateMediaSession(state.currentTrack);
        } catch (err) {
            const code = audio.error ? audio.error.code : '';
            console.warn("[Player] Playback failed:", err.message, 'mediaError=', code);
            let toastMsg = 'Playback failed — try another track or check server logs';
            if (code === 4) {
                const detail = await fetchStreamErrorDetail(streamUrl);
                toastMsg =
                    detail ||
                    'Stream failed (open Network → /tracks/stream for HTTP status; 503 = YouTube/yt-dlp on server).';
            }
            if (toastMsg.length > 320) toastMsg = `${toastMsg.slice(0, 317)}…`;
            if (typeof UI !== 'undefined' && UI.showToast) UI.showToast(toastMsg);
            state.isPlaying = false;
        }
    }
    UI.initIcons();
};

window.playNext = () => {
    if (state.queue.length > 0) {
        const next = state.queue.shift();
        playTrack(trackPlaybackId(next), next.title, next.artist, next.thumbnail);
        return;
    }
    if (state.currentTracksContext.length > 0) {
        let nextIndex = state.currentTrackIndex + 1;
        if (nextIndex >= state.currentTracksContext.length) nextIndex = 0;
        const next = state.currentTracksContext[nextIndex];
        playTrack(trackPlaybackId(next), next.title, next.artist, next.thumbnail);
    }
};

window.playPrevious = () => {
    if (state.currentTracksContext.length > 0) {
        let prevIndex = state.currentTrackIndex - 1;
        if (prevIndex < 0) prevIndex = state.currentTracksContext.length - 1;
        const prev = state.currentTracksContext[prevIndex];
        playTrack(trackPlaybackId(prev), prev.title, prev.artist, prev.thumbnail);
    }
};

window.addToQueue = (id, title, artist, thumbnail, top = false) => {
    const track = { id, title, artist, thumbnail: thumbnail || 'https://images.unsplash.com/photo-1493225255756-d9584f8606e9?w=300&q=80' };
    if (top) state.queue.unshift(track);
    else state.queue.push(track);

    UI.renderQueue();
    UI.showToast("Added to queue");

    // Auto-open sidebar if it's closed
    const sidebar = document.getElementById('queue-sidebar');
    if (sidebar && !sidebar.classList.contains('active')) {
        UI.toggleQueue();
    }
};

window.playAll = () => {
    if (state.currentTracksContext.length > 0) {
        state.queue = []; // Clear queue when playing context
        const first = state.currentTracksContext[0];
        playTrack(trackPlaybackId(first), first.title, first.artist, first.thumbnail);
    }
};

window.playRandom = async () => {
    if (state.currentTracksContext.length > 0) {
        state.queue = [];
        // Fisher-Yates Shuffle
        const shuffled = [...state.currentTracksContext];
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        state.currentTracksContext = shuffled;
        const first = shuffled[0];
        UI.showToast("Shuffling playback");
        await playTrack(trackPlaybackId(first), first.title, first.artist, first.thumbnail);
    }
};

window.removeFromQueue = (index) => {
    state.queue.splice(index, 1);
    UI.renderQueue();
};

window.showPlaylistSelector = (trackId) => UI.showPlaylistSelector(trackId);

window.addTrackToPlaylist = async (playlistId, trackId) => {
    const res = await API.addTrackToPlaylist(playlistId, trackId);
    if (res.ok) {
        UI.showToast("Added to playlist");
        document.getElementById('playlist-modal').style.display = 'none';
    }
};
