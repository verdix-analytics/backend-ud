from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user_profile import UserProfile, UsageEvent
from app.services.database_service import get_db_session

logger = logging.getLogger(__name__)

# Credit costs per operation
CREDIT_COST_ANALYSIS = 1   # GET /stocks/{ticker}/analysis
CREDIT_COST_SUMMARY  = 2   # GET /stocks/{ticker}/summary  (AI deep commentary)

FREE_ANALYSES_PER_MONTH = 3


def get_or_create_profile(cognito_sub: str) -> UserProfile:
    """
    Lazy-create a UserProfile row the first time we see a Cognito sub.
    Returns the existing or newly created profile.
    """
    session: Session = get_db_session()
    try:
        profile = session.get(UserProfile, cognito_sub)
        if profile is None:
            profile = UserProfile(
                cognito_sub=cognito_sub,
                subscription_type="basic",
                credits_remaining=0,
                free_analyses_remaining=FREE_ANALYSES_PER_MONTH,
                free_analyses_reset_at=None,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            logger.info("Created new user profile for sub=%s", cognito_sub)
        return profile
    except Exception as exc:
        session.rollback()
        logger.error("Error in get_or_create_profile for %s: %s", cognito_sub, exc)
        raise
    finally:
        session.close()


DEFAULT_PRO_CREDITS = 10


def set_subscription(cognito_sub: str, subscription_type: str) -> None:
    """Update subscription_type for a user. Pro gets DEFAULT_PRO_CREDITS, basic gets 0."""
    session: Session = get_db_session()
    try:
        profile = session.get(UserProfile, cognito_sub)
        if profile is None:
            profile = UserProfile(cognito_sub=cognito_sub)
            session.add(profile)
        profile.subscription_type = subscription_type
        profile.credits_remaining = DEFAULT_PRO_CREDITS if subscription_type == "pro" else 0
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Error in set_subscription for %s: %s", cognito_sub, exc)
        raise
    finally:
        session.close()


def get_profile_info(cognito_sub: str) -> dict[str, Any]:
    """Return credit/subscription info for the /me endpoint."""
    profile = get_or_create_profile(cognito_sub)
    return {
        "subscription_type":       profile.subscription_type,
        "credits_remaining":       profile.credits_remaining,
        "free_analyses_remaining": profile.free_analyses_remaining,
    }


def check_and_deduct_credit(
    cognito_sub: str,
    ticker: str,
    analysis_type: str,
    credit_cost: int,
    cache_hit: bool = False,
) -> str:
    """
    Gate for credit-consuming endpoints.

    - cache_hit=True  → log the event, deduct nothing, return "cache"
    - free usages available → deduct one free usage, return "free"
    - paid credits available → deduct credit_cost credits, return "credits"
    - nothing left → raise HTTP 402

    Returns the deducted_from string so the caller can log/respond with it.
    """
    session: Session = get_db_session()
    try:
        profile = session.get(UserProfile, cognito_sub)
        if profile is None:
            # Should not happen (get_or_create_profile is called first via /me),
            # but handle defensively.
            profile = UserProfile(
                cognito_sub=cognito_sub,
                subscription_type="basic",
                credits_remaining=0,
                free_analyses_remaining=FREE_ANALYSES_PER_MONTH,
            )
            session.add(profile)

        if cache_hit:
            deducted_from = "cache"
        elif profile.free_analyses_remaining > 0:
            profile.free_analyses_remaining -= 1
            deducted_from = "free"
        elif profile.credits_remaining >= credit_cost:
            profile.credits_remaining -= credit_cost
            deducted_from = "credits"
        else:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "insufficient_credits",
                    "message": (
                        "You have used all your free analyses and have no credits remaining. "
                        "Please purchase credits to continue."
                    ),
                    "free_analyses_remaining": profile.free_analyses_remaining,
                    "credits_remaining": profile.credits_remaining,
                },
            )

        # Log the usage event
        event = UsageEvent(
            cognito_sub=cognito_sub,
            ticker=ticker.upper(),
            analysis_type=analysis_type,
            credit_cost=0 if cache_hit else credit_cost,
            deducted_from=deducted_from,
            cache_hit=cache_hit,
        )
        session.add(event)
        session.commit()

        logger.info(
            "Usage event: sub=%s ticker=%s type=%s deducted_from=%s cache_hit=%s",
            cognito_sub, ticker, analysis_type, deducted_from, cache_hit,
        )
        return deducted_from

    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Error in check_and_deduct_credit for %s: %s", cognito_sub, exc)
        raise
    finally:
        session.close()


def reset_monthly_free_analyses() -> int:
    """
    Reset free_analyses_remaining = FREE_ANALYSES_PER_MONTH for all pro users.
    Called by a monthly scheduled job.
    Returns the number of profiles reset.
    """
    session: Session = get_db_session()
    try:
        profiles = (
            session.query(UserProfile)
            .filter(UserProfile.subscription_type == "pro")
            .all()
        )
        now = datetime.now(timezone.utc)
        for p in profiles:
            p.free_analyses_remaining = FREE_ANALYSES_PER_MONTH
            p.free_analyses_reset_at  = now
        session.commit()
        logger.info("Reset free analyses for %d pro users", len(profiles))
        return len(profiles)
    except Exception as exc:
        session.rollback()
        logger.error("Error resetting monthly free analyses: %s", exc)
        raise
    finally:
        session.close()
