// player.js - Audio Logic & Media Session v2.7.5
const PLAYER = {
    init: () => {
        const audio = document.getElementById('main-audio');
        if (!audio) return;

        audio.addEventListener('timeupdate', () => {
            const percent = (audio.currentTime / audio.duration) * 100;
            const seekFill = document.getElementById('seek-fill');
            const currentTimeEl = document.getElementById('current-time');
            const totalTimeEl = document.getElementById('total-time');

            if (seekFill) seekFill.style.width = `${percent || 0}%`;
            if (currentTimeEl) currentTimeEl.innerText = PLAYER.formatTime(audio.currentTime);
            if (totalTimeEl) totalTimeEl.innerText = PLAYER.formatTime(audio.duration);
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
                if (!isNaN(audio.duration)) {
                    audio.currentTime = percent * audio.duration;
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
        if (isNaN(seconds)) return '0:00';
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

window.playTrack = async (trackId, title, artist, thumbnail) => {
    state.currentTrack = { id: trackId, title, artist, thumbnail };
    state.isPlaying = true;

    const playerMetadata = document.getElementById('player-metadata');
    if (playerMetadata) playerMetadata.style.visibility = 'visible';

    const audio = document.getElementById('main-audio');
    const playBtn = document.getElementById('btn-play');

    state.currentTrackIndex = state.currentTracksContext.findIndex(t => (t.id || t.remote_id) === trackId);

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
        audio.src = `${CONFIG.apiBase}/stream/${trackId}`;
        try {
            await audio.play();
            if (playBtn) playBtn.innerHTML = '<i data-lucide="pause"></i>';
            PLAYER.updateMediaSession(state.currentTrack);
        } catch (err) {
            console.warn("[Player] Playback failed:", err.message);
            state.isPlaying = false;
        }
    }
    UI.initIcons();
};

window.playNext = () => {
    if (state.queue.length > 0) {
        const next = state.queue.shift();
        playTrack(next.id, next.title, next.artist, next.thumbnail);
        return;
    }
    if (state.currentTracksContext.length > 0) {
        let nextIndex = state.currentTrackIndex + 1;
        if (nextIndex >= state.currentTracksContext.length) nextIndex = 0;
        const next = state.currentTracksContext[nextIndex];
        playTrack(next.id || next.remote_id, next.title, next.artist, next.thumbnail);
    }
};

window.playPrevious = () => {
    if (state.currentTracksContext.length > 0) {
        let prevIndex = state.currentTrackIndex - 1;
        if (prevIndex < 0) prevIndex = state.currentTracksContext.length - 1;
        const prev = state.currentTracksContext[prevIndex];
        playTrack(prev.id || prev.remote_id, prev.title, prev.artist, prev.thumbnail);
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
        playTrack(first.id || first.remote_id, first.title, first.artist, first.thumbnail);
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
