import pytest

from app.models.project import ProjectStatus, ShotStatus
from app.providers.llm.mock import MockLLMProvider
from app.services import project_service
from app.services.project_service import InvalidTransitionError

IDEA = "He buried a pink submarine in his backyard and turned it into an underground luxury bunker."


def test_create_project_starts_in_idea_status(db_session):
    project = project_service.create_project(db_session, IDEA)
    assert project.status == ProjectStatus.IDEA
    assert project.idea_text == IDEA
    assert project.id  # a UUID was assigned


def test_full_pipeline_through_storyboard(db_session):
    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)

    project = project_service.advance_to_concept(db_session, project, llm)
    assert project.status == ProjectStatus.CONCEPT_APPROVED
    assert project.concept
    assert project.continuity_bible["original_idea"] == IDEA
    assert project.continuity_bible["main_subject"] == "pink submarine"
    assert project.continuity_bible["end_use"] == "underground luxury bunker"

    project = project_service.advance_to_script(db_session, project, llm)
    assert project.status == ProjectStatus.SCRIPT_READY
    assert "hook" in project.script
    assert len(project.script["beats"]) > 0

    project = project_service.advance_to_storyboard(db_session, project, llm)
    assert project.status == ProjectStatus.STORYBOARD_READY
    assert 10 <= len(project.shots) <= 20
    assert all(shot.status == ShotStatus.PROMPT_READY for shot in project.shots)
    # shot numbers are sequential starting at 1
    assert [s.shot_number for s in project.shots] == list(range(1, len(project.shots) + 1))


def test_shot_prompts_inherit_continuity_bible(db_session):
    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)
    project = project_service.advance_to_concept(db_session, project, llm)
    project = project_service.advance_to_script(db_session, project, llm)
    project = project_service.advance_to_storyboard(db_session, project, llm)

    location = project.continuity_bible["location"]
    for shot in project.shots:
        assert location in shot.prompt
        assert shot.description in shot.prompt


def test_cost_records_written_with_zero_cost_for_mock_provider(db_session):
    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)
    project = project_service.advance_to_concept(db_session, project, llm)

    assert len(project.cost_records) == 1
    assert project.cost_records[0].cost_usd == 0.0
    assert project.cost_records[0].provider_name == "mock-llm"
    assert project.total_cost_usd == 0.0


def test_cannot_skip_states(db_session):
    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)

    with pytest.raises(InvalidTransitionError):
        project_service.advance_to_script(db_session, project, llm)


def test_cannot_repeat_a_completed_transition(db_session):
    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)
    project = project_service.advance_to_concept(db_session, project, llm)

    with pytest.raises(InvalidTransitionError):
        project_service.advance_to_concept(db_session, project, llm)
