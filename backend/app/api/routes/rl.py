"""Reinforcement Learning training and evaluation API endpoints."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database.models import (
    AgentType,
    EvaluationResult,
    Topology,
    TrainingEpisode,
    TrainingSession,
    TrainingStatus,
)
from app.database.schemas import (
    EvaluationRequest,
    EvaluationResultResponse,
    TrainingEpisodeResponse,
    TrainingProgressResponse,
    TrainingRequest,
    TrainingSessionResponse,
    ComparisonResponse,
)
from app.database.session import get_db, async_session_factory
from app.rl.trainer import build_dqn_trainer, build_ppo_trainer
from app.simulation.evaluator import Evaluator
from app.topology.generator import TopologyGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rl", tags=["reinforcement-learning"])

# Track running training sessions
_active_trainers: dict[str, Any] = {}
generator = TopologyGenerator()


async def _run_training(session_id: str, request: TrainingRequest) -> None:
    """Background task: run RL training and persist results."""
    async with async_session_factory() as db:
        session = await db.get(TrainingSession, session_id)
        if not session:
            return

        session.status = TrainingStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        await db.commit()

        topo_row = await db.get(Topology, request.topology_id)
        if not topo_row:
            session.status = TrainingStatus.FAILED
            await db.commit()
            return

    # Reconstruct topology definition from stored config
    from app.database.schemas import TopologyConfig

    try:
        cfg = TopologyConfig(**topo_row.config)
        topo_def = generator.generate(cfg)
    except Exception as e:
        logger.error("Failed to rebuild topology for training: %s", e)
        async with async_session_factory() as db:
            session = await db.get(TrainingSession, session_id)
            if session:
                session.status = TrainingStatus.FAILED
                await db.commit()
        return

    episode_buffer: list[dict] = []

    async def progress_cb(info: dict) -> None:
        episode_buffer.append(info)
        if len(episode_buffer) >= 10:
            async with async_session_factory() as db:
                sess = await db.get(TrainingSession, session_id)
                if not sess:
                    return
                sess.current_timestep = info.get("step", 0)
                for ep_info in episode_buffer:
                    ep = TrainingEpisode(
                        session_id=session_id,
                        episode_number=ep_info.get("episode", 0),
                        total_reward=ep_info.get("mean_reward", 0.0),
                        avg_latency_ms=ep_info.get("mean_latency_ms", 0.0),
                        avg_throughput_mbps=ep_info.get("mean_throughput", 0.0),
                        avg_packet_loss=ep_info.get("mean_packet_loss", 0.0),
                        avg_link_utilization=ep_info.get("mean_utilization", 0.0),
                        steps=ep_info.get("episode", 0),
                        epsilon=ep_info.get("epsilon"),
                        policy_loss=ep_info.get("policy_loss"),
                        value_loss=ep_info.get("value_loss"),
                    )
                    if ep.total_reward > (sess.best_reward or float("-inf")):
                        sess.best_reward = ep.total_reward
                    db.add(ep)
                await db.commit()
            episode_buffer.clear()

    try:
        if request.agent_type == AgentType.DQN:
            env, agent, trainer = build_dqn_trainer(
                topo_def,
                total_timesteps=request.total_timesteps,
                hyperparams=request.hyperparameters,
                session_id=session_id,
                progress_callback=lambda info: asyncio.create_task(progress_cb(info)),
            )
        elif request.agent_type == AgentType.PPO:
            env, agent, trainer = build_ppo_trainer(
                topo_def,
                total_timesteps=request.total_timesteps,
                hyperparams=request.hyperparameters,
                session_id=session_id,
                progress_callback=lambda info: asyncio.create_task(progress_cb(info)),
            )
        else:
            raise ValueError(f"Unsupported agent type: {request.agent_type}")

        _active_trainers[session_id] = trainer
        metrics = await trainer.train()

        async with async_session_factory() as db:
            sess = await db.get(TrainingSession, session_id)
            if sess:
                sess.status = TrainingStatus.COMPLETED
                sess.completed_at = datetime.now(timezone.utc)
                sess.current_timestep = request.total_timesteps
                await db.commit()

    except Exception as e:
        logger.exception("Training failed for session %s: %s", session_id, e)
        async with async_session_factory() as db:
            sess = await db.get(TrainingSession, session_id)
            if sess:
                sess.status = TrainingStatus.FAILED
                await db.commit()
    finally:
        _active_trainers.pop(session_id, None)


@router.post("/train", response_model=TrainingSessionResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_training(
    request: TrainingRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrainingSession:
    """Start an RL training session."""
    topo = await db.get(Topology, request.topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    session = TrainingSession(
        agent_type=request.agent_type,
        topology_id=request.topology_id,
        total_timesteps=request.total_timesteps,
        hyperparameters=request.hyperparameters,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    background_tasks.add_task(_run_training, str(session.id), request)
    logger.info("Started training session %s (%s)", session.id, request.agent_type)
    return session


@router.post("/train/{session_id}/stop", response_model=TrainingSessionResponse)
async def stop_training(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrainingSession:
    trainer = _active_trainers.get(session_id)
    if trainer:
        trainer.stop()

    session = await db.get(TrainingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    session.status = TrainingStatus.PAUSED
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[TrainingSessionResponse])
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
) -> list[TrainingSession]:
    result = await db.execute(
        select(TrainingSession).order_by(desc(TrainingSession.created_at)).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/sessions/{session_id}", response_model=TrainingProgressResponse)
async def get_session_progress(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrainingProgressResponse:
    session = await db.get(TrainingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    result = await db.execute(
        select(TrainingEpisode)
        .where(TrainingEpisode.session_id == session_id)
        .order_by(desc(TrainingEpisode.timestamp))
        .limit(50)
    )
    episodes = list(result.scalars().all())
    progress_pct = (
        session.current_timestep / session.total_timesteps * 100
        if session.total_timesteps > 0
        else 0.0
    )

    return TrainingProgressResponse(
        session=TrainingSessionResponse.model_validate(session),
        recent_episodes=[TrainingEpisodeResponse.model_validate(e) for e in episodes],
        progress_pct=round(progress_pct, 2),
    )


@router.post("/evaluate", response_model=list[EvaluationResultResponse])
async def run_evaluation(
    request: EvaluationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EvaluationResult]:
    """Run evaluation comparing multiple routing strategies."""
    topo_row = await db.get(Topology, request.topology_id)
    if not topo_row:
        raise HTTPException(status_code=404, detail="Topology not found")

    from app.database.schemas import TopologyConfig

    try:
        cfg = TopologyConfig(**topo_row.config)
        topo_def = generator.generate(cfg)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to build topology: {e}")

    evaluator = Evaluator(topo_def)
    # Load trained agents if available
    agents: dict[AgentType, Any] = {}
    for agent_type in request.agents:
        if agent_type in (AgentType.DQN, AgentType.PPO):
            agents[agent_type] = await _load_agent(agent_type, topo_def)

    results = await evaluator.compare_all(agents, num_episodes=request.num_episodes)

    db_results: list[EvaluationResult] = []
    for agent_type, eval_result in results.items():
        db_result = EvaluationResult(
            agent_type=agent_type,
            topology_id=request.topology_id,
            avg_latency_ms=eval_result.avg_latency_ms,
            avg_throughput_mbps=eval_result.avg_throughput_pct,
            avg_packet_loss=eval_result.avg_packet_loss,
            avg_link_utilization=eval_result.avg_throughput_pct / 100.0,
            convergence_time_s=eval_result.convergence_time_s,
            num_episodes=len(eval_result.episodes),
            raw_metrics={"episodes": [vars(e) for e in eval_result.episodes]},
        )
        db.add(db_result)
        db_results.append(db_result)

    await db.commit()
    for r in db_results:
        await db.refresh(r)
    return db_results


@router.get("/compare/{topology_id}", response_model=ComparisonResponse)
async def get_comparison(
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComparisonResponse:
    result = await db.execute(
        select(EvaluationResult)
        .where(EvaluationResult.topology_id == topology_id)
        .order_by(desc(EvaluationResult.created_at))
    )
    eval_results = list(result.scalars().all())
    if not eval_results:
        raise HTTPException(status_code=404, detail="No evaluation results for this topology")

    # Find best agent by throughput
    best = max(eval_results, key=lambda r: r.avg_throughput_mbps)
    baseline = next((r for r in eval_results if r.agent_type == AgentType.SHORTEST_PATH), None)

    improvements: dict[str, float] = {}
    if baseline:
        for r in eval_results:
            if r.agent_type != AgentType.SHORTEST_PATH:
                improvements[r.agent_type.value] = round(
                    (r.avg_throughput_mbps - baseline.avg_throughput_mbps)
                    / max(baseline.avg_throughput_mbps, 1) * 100,
                    2,
                )

    return ComparisonResponse(
        topology_id=topology_id,
        results=[EvaluationResultResponse.model_validate(r) for r in eval_results],
        best_agent=best.agent_type,
        improvement_over_shortest_path=improvements,
    )


async def _load_agent(agent_type: AgentType, topo_def: Any) -> Any | None:
    """Attempt to load a saved RL agent model."""
    from app.config import get_settings
    from app.rl.environment import SDNRoutingEnv

    settings = get_settings()
    env = SDNRoutingEnv(topo_def)
    obs_dim = env.observation_space.shape[0]
    action_dims = list(env.action_space.nvec)

    if agent_type == AgentType.DQN:
        from app.rl.agents.dqn_agent import DQNAgent

        model_path = settings.rl_models_dir / "dqn_model.pt"
        if not model_path.exists():
            return None
        agent = DQNAgent(obs_dim=obs_dim, action_dims=action_dims)
        try:
            agent.load(model_path)
            return agent
        except Exception as e:
            logger.warning("Could not load DQN model: %s", e)
            return None

    elif agent_type == AgentType.PPO:
        from app.rl.agents.ppo_agent import PPOAgent

        model_path = settings.rl_models_dir / "ppo_model.pt"
        if not model_path.exists():
            return None
        agent = PPOAgent(obs_dim=obs_dim, action_dims=action_dims)
        try:
            agent.load(model_path)
            return agent
        except Exception as e:
            logger.warning("Could not load PPO model: %s", e)
            return None

    return None
