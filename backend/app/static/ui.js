// ui.js - DOM & Rendering
const UI = {
    initIcons: () => {
        if (window.lucide) {
            window.lucide.createIcons();
        }
    },

    showToast: (message) => {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.innerText = message;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    },

    renderTracks: (tracks, title = null, append = false) => {
        if (!tracks || !Array.isArray(tracks)) {
            console.error("[UI] Invalid tracks data provided to renderTracks:", tracks);
            if (!append) document.getElementById('track-list').innerHTML = '';
            return;
        }
        console.log(`[UI] Rendering ${tracks.length} tracks for: ${title || 'Current View'} (append=${append})`);
        const list = document.getElementById('track-list');
        const viewTitle = document.querySelector('#content-view h1');
        if (!list) return;

        if (viewTitle) {
            if (title) {
                viewTitle.style.display = 'block';
                if (state.currentView === 'playlist' || state.currentView === 'liked') {
                    viewTitle.style.display = 'flex';
                    viewTitle.style.alignItems = 'center';
                    viewTitle.style.gap = '16px';
                    viewTitle.style.flexWrap = 'wrap';
                    viewTitle.innerHTML = `
                        <span style="flex-shrink: 0;">${title}</span>
                        <div style="display: flex; gap: 12px; align-items: center;">
                            <button class="btn-primary header-btn" style="width: auto; position: relative; z-index: 10;" onclick="playAll()">
                                <i data-lucide="play" style="width: 16px; height: 16px; margin-right: 8px;"></i> Play All
                            </button>
                            <button class="btn-primary header-btn" style="width: auto; background: var(--bg-glass); border: 1px solid var(--primary); position: relative; z-index: 10;" onclick="playRandom()">
                                <i data-lucide="shuffle" style="width: 16px; height: 16px; margin-right: 8px;"></i> Play Random
                            </button>
                            ${state.currentView === 'playlist' ? `
                                <button class="btn-primary header-btn" style="width: auto; background: #ef444422; border: 1px solid #ef4444; color: #ef4444; position: relative; z-index: 10;" onclick="deleteCurrentPlaylist()">
                                    <i data-lucide="trash-2" style="width: 16px; height: 16px; margin-right: 8px;"></i> Delete
                                </button>
                            ` : ''}
                        </div>`;
                } else {
                    viewTitle.style.display = 'block';
                    viewTitle.innerText = title;
                }
            } else {
                viewTitle.style.display = 'none';
            }
        }

        if (!append && (!tracks || tracks.length === 0)) {
            list.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">No tracks found</div>';
            return;
        }

        const html = tracks.map(track => {
            const id = track.id || track.remote_id;
            const isLiked = state.likedTrackIds.has(id) || track.is_liked;
            if (track.is_liked) state.likedTrackIds.add(id);

            const safeTitle = track.title ? track.title.toString().replace(/'/g, "\\'") : "";
            const safeArtist = track.artist ? track.artist.toString().replace(/'/g, "\\'") : "";
            const thumb = (track.thumbnail && track.thumbnail !== 'null' && track.thumbnail !== 'undefined')
                ? track.thumbnail
                : 'https://images.unsplash.com/photo-1493225255756-d9584f8606e9?w=300&q=80';

            const sourceIcon = track.source_type === 'local' ? 'hard-drive' : 'cloud';
            const cacheBadge = track.is_cached ? `<span class="badge-cached" title="Cached on SSD"><i data-lucide="check-circle" style="width: 10px; height: 10px;"></i> Cached</span>` : "";

            return `
                <div class="track-card animate-fade">
                    <div class="card-image-container" onclick="playTrack('${id}', '${safeTitle}', '${safeArtist}', '${thumb}')">
                        <img src="${thumb}" class="track-image">
                        <div class="source-indicator" title="Source: ${track.source_type}">
                            <i data-lucide="${sourceIcon}"></i>
                        </div>
                        ${cacheBadge}
                        <div class="card-play-overlay">
                            <i data-lucide="play-circle"></i>
                        </div>
                    </div>
                    <div class="card-actions">
                        <button class="card-action-btn" title="Share" onclick="event.stopPropagation(); shareItem('${id}', 'track', '${safeTitle}', '${safeArtist}')">
                            <i data-lucide="share-2"></i>
                        </button>
                        <button class="card-action-btn" title="Add to Queue" onclick="event.stopPropagation(); addToQueue('${id}', '${safeTitle}', '${safeArtist}', '${track.thumbnail}')">
                            <i data-lucide="list-plus"></i>
                        </button>
                        <button class="card-action-btn" title="Play Next" onclick="event.stopPropagation(); addToQueue('${id}', '${safeTitle}', '${safeArtist}', '${track.thumbnail}', true)">
                            <i data-lucide="list-start"></i>
                        </button>
                        ${state.currentView === 'playlist' ? `
                            <button class="card-action-btn" title="Remove from Playlist" onclick="event.stopPropagation(); removeFromPlaylist('${id}')">
                                <i data-lucide="minus-square"></i>
                            </button>
                        ` : `
                            <button class="card-action-btn" title="Add to Playlist" onclick="event.stopPropagation(); showPlaylistSelector('${id}')">
                                <i data-lucide="plus-square"></i>
                            </button>
                        `}
                        <button class="card-action-btn ${isLiked ? 'active' : ''}" title="Like" onclick="event.stopPropagation(); toggleLike('${id}', this)">
                            <i data-lucide="heart" ${isLiked ? 'fill="currentColor"' : ''}></i>
                        </button>
                    </div>
                    <div class="track-info">
                        <div class="title">${track.title || "Unknown Title"}</div>
                        <div class="artist">${track.artist || "Unknown Artist"}</div>
                    </div>
                </div>
            `;
        }).join('');

        if (append) {
            list.insertAdjacentHTML('beforeend', html);
            state.currentTracksContext = [...state.currentTracksContext, ...tracks];
        } else {
            list.innerHTML = html;
            state.currentTracksContext = tracks;
            // Reset scroll on NEW view
            const scrollContainer = document.querySelector('.main-content');
            if (scrollContainer) scrollContainer.scrollTop = 0;
        }
        UI.initIcons();
    },

    setLoading: (isLoading) => {
        const trigger = document.getElementById('infinite-scroll-trigger');
        if (trigger) {
            // Keep the basic structure but show/hide content
            if (isLoading) {
                trigger.innerHTML = '<div class="spinner"></div><span>Fetching more magic...</span>';
            } else {
                // Restore manual load button as a fallback
                trigger.innerHTML = `
                    <span>End of the road?</span>
                    <button class="btn-primary" onclick="loadHomeTracks(true)" style="width: auto; padding: 8px 16px; font-size: 13px;">
                        Try Manual Load
                    </button>
                `;
            }
            trigger.style.display = 'flex';
        }
    },

    toggleSidebar: () => {
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        if (!sidebar) return;

        if (window.innerWidth <= 768) {
            const isExpanded = sidebar.classList.toggle('expanded');
            overlay?.classList.toggle('active', isExpanded);
        } else {
            sidebar.classList.toggle('collapsed');
        }
    },

    showPlaylistSelector: async (trackId) => {
        const modal = document.getElementById('playlist-modal');
        const list = document.getElementById('playlist-selector-list');
        if (!modal || !list) return;

        modal.style.display = 'flex';
        list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Loading...</div>';

        try {
            const res = await API.getPlaylists();
            const playlists = await res.json();
            list.innerHTML = playlists.map(p => `
                <div class="playlist-item" onclick="addTrackToPlaylist('${p.id}', '${trackId}')">
                    <i data-lucide="music"></i>
                    <div class="playlist-info">
                        <strong>${p.name}</strong>
                    </div>
                </div>
            `).join('');
            UI.initIcons();
        } catch (e) {
            list.innerHTML = 'Failed to load playlists.';
        }
    },

    renderQueue: () => {
        const list = document.getElementById('queue-list');
        if (!list) return;
        if (state.queue.length === 0) {
            list.innerHTML = '<div class="empty-queue">Queue is empty</div>';
            return;
        }
        list.innerHTML = state.queue.map((track, index) => {
            const thumb = (track.thumbnail && track.thumbnail !== 'null' && track.thumbnail !== 'undefined')
                ? track.thumbnail
                : 'https://images.unsplash.com/photo-1493225255756-d9584f8606e9?w=300&q=80';

            return `
                <div class="queue-item">
                    <img src="${thumb}" class="queue-img">
                    <div class="queue-info">
                        <div class="q-title">${track.title}</div>
                        <div class="q-artist">${track.artist}</div>
                    </div>
                    <button onclick="removeFromQueue(${index})"><i data-lucide="x"></i></button>
                </div>
            `;
        }).join('');
        UI.initIcons();
    },

    toggleQueue: () => {
        const sidebar = document.getElementById('queue-sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        if (!sidebar) return;

        const isActive = sidebar.classList.toggle('active');
        if (overlay) overlay.classList.toggle('active', isActive);

        if (isActive) UI.renderQueue();
    },

    deleteCurrentPlaylist: async () => {
        if (!state.currentPlaylistId) return;

        const confirmDelete = window.confirm("Are you sure you want to delete this playlist? This action cannot be undone.");
        if (!confirmDelete) return;

        try {
            const res = await API.deletePlaylist(state.currentPlaylistId);
            if (res.ok) {
                UI.showToast("Playlist deleted successfully");
                // Navigate back to library
                const navLibrary = document.querySelector('.nav-item[data-view="library"]');
                if (navLibrary) navLibrary.click();
            } else {
                const err = await res.json();
                UI.showToast("Error: " + (err.detail || "Failed to delete"));
            }
        } catch (e) {
            UI.showToast("Connection error");
        }
    }
};

window.UI = UI;
window.toggleQueue = UI.toggleQueue;
window.deleteCurrentPlaylist = UI.deleteCurrentPlaylist;
window.playRandom = window.playRandom || (() => console.warn("playRandom not loaded"));
