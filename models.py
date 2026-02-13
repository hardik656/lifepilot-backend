from sqlalchemy import Column, Integer, String, Float
from database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    merchant = Column(String)
    amount = Column(Float)
