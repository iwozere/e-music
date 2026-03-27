import uuid
import asyncio
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Form
from sqlmodel import Session, select, delete

from app.models import User, Track, Playlist, PlaylistTrack
from app.db import get_session
from app.dependencies import get_current_user
from app.services.track_service import ensure_track_exists
from app.services import ytmusic
from app.services.ytmusic import get_track_thumbnail
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/playlists", tags=["playlists"])

@router.get("", response_model=List[dict])
async def get_playlists(
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all playlists owned by the current user.
    """
    statement = select(Playlist).where(Playlist.owner_id == current_user.id)
    playlists = session.exec(statement).all()
    return [p.dict() for p in playlists]

@router.post("")
async def create_playlist(
    name: str = Form(...), 
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Create a new playlist for the current user.
    """
    new_playlist = Playlist(
        id=str(uuid.uuid4()),
        name=name,
        owner_id=current_user.id
    )
    session.add(new_playlist)
    session.commit()
    session.refresh(new_playlist)
    return new_playlist.dict()

@router.post("/{playlist_id}/tracks")
async def add_track_to_playlist(
    playlist_id: str,
    track_id: str = Form(...),
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Add a track to a specific playlist.
    """
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    track = await ensure_track_exists(session, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track could not be found or indexed.")

    count_stmt = select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    existing_tracks = session.exec(count_stmt).all()
    next_pos = len(existing_tracks)

    new_rel = PlaylistTrack(playlist_id=playlist_id, track_id=track.id, position=next_pos)
    session.add(new_rel)
    session.commit()
    return {"status": "success"}

@router.delete("/{playlist_id}/tracks/{track_id}")
async def delete_track_from_playlist(
    playlist_id: str,
    track_id: str,
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Remove a track from a specific playlist.
    """
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    track = await ensure_track_exists(session, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track could not be resolved.")

    statement = select(PlaylistTrack).where(
        PlaylistTrack.playlist_id == playlist_id, 
        PlaylistTrack.track_id == track.id
    )
    relation = session.exec(statement).first()
    
    if not relation:
        raise HTTPException(status_code=404, detail="Track not in playlist")

    session.delete(relation)
    session.commit()
    return {"status": "success"}

@router.get("/{playlist_id}/tracks")
async def get_playlist_tracks(
    playlist_id: str,
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all tracks in a specific playlist, ordered by position.
    """
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    statement = (
        select(Track, PlaylistTrack.position)
        .join(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    result = session.exec(statement).all()
    
    tracks_list = []
    updated = False
    for track, position in result:
        t_dict = track.dict()
        t_dict["playlist_position"] = position
        
        if track.source_type == "youtube" and not track.thumbnail and track.remote_id:
            thumb = await get_track_thumbnail(track.remote_id)
            if thumb:
                track.thumbnail = thumb
                t_dict["thumbnail"] = thumb
                session.add(track)
                updated = True
            
        tracks_list.append(t_dict)
    
    if updated:
        session.commit()
        
    return tracks_list

@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: str,
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Delete a user's playlist.
    """
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    session.delete(playlist)
    session.exec(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
    session.commit()
    return {"status": "success"}
