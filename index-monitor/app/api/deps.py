from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_client_id(token: str = Depends(oauth2_scheme)) -> str:
    payload = decode_token(token)
    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的 token")
    return client_id
