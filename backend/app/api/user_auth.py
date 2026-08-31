from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User
from ..multitenancy import create_user_token, hash_password, require_user, verify_password
router=APIRouter(prefix="/user-auth",tags=["user-auth"])
Db=Annotated[Session,Depends(get_db)]
class RegisterIn(BaseModel):
 first_name:str=Field(min_length=1,max_length=255); last_name:str=Field(min_length=1,max_length=255); email:EmailStr; password:str=Field(min_length=8,max_length=128)
class LoginIn(BaseModel): email:EmailStr; password:str
def _out(user): return {"id":user.id,"first_name":user.first_name,"last_name":user.last_name,"email":user.email}
@router.post("/register")
def register(payload:RegisterIn,db:Db):
 email=str(payload.email).lower()
 if db.query(User).filter_by(email=email).first():raise HTTPException(409,"Пользователь с таким email уже зарегистрирован")
 user=User(first_name=payload.first_name,last_name=payload.last_name,email=email,password_hash=hash_password(payload.password)); db.add(user); db.commit(); db.refresh(user)
 return {"token":create_user_token(user.id),"user":_out(user)}
@router.post("/login")
def login(payload:LoginIn,db:Db):
 user=db.query(User).filter_by(email=str(payload.email).lower()).first()
 if user is None or not verify_password(payload.password,user.password_hash):raise HTTPException(401,"Неверный email или пароль")
 return {"token":create_user_token(user.id),"user":_out(user)}
@router.get("/me")
def me(user_id:Annotated[int,Depends(require_user)],db:Db):
 user=db.get(User,user_id)
 if user is None:raise HTTPException(401,"Пользователь не найден")
 return _out(user)
