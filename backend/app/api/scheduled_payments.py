from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import ScheduledPayment
from app.schemas.scheduled_payment import ScheduledPaymentCreate, ScheduledPaymentRead, ScheduledPaymentUpdate
from app.services.scheduler_service import list_scheduled_payments, recipient_belongs_to_user


router = APIRouter(prefix="/scheduled-payments", tags=["scheduled payments"])


@router.post("", response_model=ScheduledPaymentRead, status_code=201)
def create_schedule(payload: ScheduledPaymentCreate, session: Session = Depends(get_db)) -> ScheduledPayment:
	if not recipient_belongs_to_user(session, payload.user_id, payload.recipient_id):
		raise HTTPException(status_code=404, detail="User or recipient not found")
	schedule = ScheduledPayment(**payload.model_dump())
	session.add(schedule)
	session.commit()
	session.refresh(schedule)
	return schedule


@router.get("", response_model=list[ScheduledPaymentRead])
def get_schedules(user_id: str, session: Session = Depends(get_db)) -> list[ScheduledPayment]:
	return list_scheduled_payments(session, user_id)


@router.patch("/{schedule_id}", response_model=ScheduledPaymentRead)
def update_schedule(
	schedule_id: str,
	payload: ScheduledPaymentUpdate,
	session: Session = Depends(get_db),
) -> ScheduledPayment:
	schedule = session.get(ScheduledPayment, schedule_id)
	if schedule is None:
		raise HTTPException(status_code=404, detail="Scheduled payment not found")
	updates = payload.model_dump(exclude_unset=True)
	if not updates:
		raise HTTPException(status_code=422, detail="Provide active or next_run_at")
	for field, value in updates.items():
		setattr(schedule, field, value)
	session.commit()
	session.refresh(schedule)
	return schedule


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, session: Session = Depends(get_db)) -> Response:
	schedule = session.get(ScheduledPayment, schedule_id)
	if schedule is None:
		raise HTTPException(status_code=404, detail="Scheduled payment not found")
	session.delete(schedule)
	session.commit()
	return Response(status_code=204)
