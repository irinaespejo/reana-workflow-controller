# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller utility tests."""

import io
import json
import os
import uuid

import fs
import mock
import pytest
from flask import url_for
from pytest_reana.fixtures import (cwl_workflow_with_name,
                                   cwl_workflow_without_name, default_user,
                                   sample_yadage_workflow_in_db, session,
                                   tmp_shared_volume_path,
                                   yadage_workflow_with_name)
from reana_db.models import Job, JobCache, Workflow, WorkflowStatus
from werkzeug.utils import secure_filename

from reana_workflow_controller.errors import WorkflowDeletionError
from reana_workflow_controller.rest import START, STOP, _delete_workflow
from reana_workflow_controller.utils import create_workflow_workspace


@pytest.mark.parametrize("status", [WorkflowStatus.created,
                                    WorkflowStatus.failed,
                                    WorkflowStatus.finished,
                                    WorkflowStatus.stopped,
                                    pytest.param(WorkflowStatus.deleted,
                                                 marks=pytest.mark.xfail),
                                    pytest.param(WorkflowStatus.running,
                                                 marks=pytest.mark.xfail)])
@pytest.mark.parametrize("hard_delete", [True, False])
def test_delete_workflow(app,
                         session,
                         default_user,
                         sample_yadage_workflow_in_db,
                         status,
                         hard_delete):
    """Test deletion of a workflow in all possible statuses."""
    sample_yadage_workflow_in_db.status = status
    session.add(sample_yadage_workflow_in_db)
    session.commit()

    _delete_workflow(sample_yadage_workflow_in_db, hard_delete=hard_delete)
    if not hard_delete:
        assert sample_yadage_workflow_in_db.status == WorkflowStatus.deleted
    else:
        assert session.query(Workflow).filter_by(
            id_=sample_yadage_workflow_in_db.id_).all() == []


@pytest.mark.parametrize("hard_delete", [True, False])
def test_delete_all_workflow_runs(app,
                                  session,
                                  default_user,
                                  yadage_workflow_with_name,
                                  hard_delete):
    """Test deletion of all runs of a given workflow."""
    # add 5 workflows in the database with the same name
    for i in range(5):
        workflow = Workflow(id_=uuid.uuid4(),
                            name=yadage_workflow_with_name['name'],
                            owner_id=default_user.id_,
                            reana_specification=yadage_workflow_with_name[
                                'reana_specification'],
                            operational_options={},
                            type_=yadage_workflow_with_name[
                                'reana_specification']['workflow']['type'],
                            logs='')
        session.add(workflow)
        if i == 4:
            workflow.status = WorkflowStatus.running
            not_deleted_one = workflow.id_
        session.commit()

    first_workflow = session.query(Workflow).\
        filter_by(name=yadage_workflow_with_name['name']).first()
    _delete_workflow(first_workflow,
                     all_runs=True,
                     hard_delete=hard_delete)
    if not hard_delete:
        for workflow in session.query(Workflow).\
                filter_by(name=first_workflow.name).all():
            if not_deleted_one == workflow.id_:
                assert workflow.status == WorkflowStatus.running
            else:
                assert workflow.status == WorkflowStatus.deleted
    else:
        # the one running should not be deleted
        assert len(session.query(Workflow).
                   filter_by(name=first_workflow.name).all()) == 1


@pytest.mark.parametrize("hard_delete", [True, False])
@pytest.mark.parametrize("workspace", [True, False])
def test_workspace_deletion(app,
                            session,
                            default_user,
                            sample_yadage_workflow_in_db,
                            tmp_shared_volume_path,
                            workspace,
                            hard_delete):
    """Test workspace deletion."""
    workflow = sample_yadage_workflow_in_db
    create_workflow_workspace(sample_yadage_workflow_in_db.get_workspace())
    absolute_workflow_workspace = os.path.join(
        tmp_shared_volume_path,
        workflow.get_workspace())

    # create a job for the workflow
    workflow_job = Job(id_=uuid.uuid4(), workflow_uuid=workflow.id_)
    job_cache_entry = JobCache(job_id=workflow_job.id_)
    session.add(workflow_job)
    session.add(job_cache_entry)
    session.commit()

    # check that the workflow workspace exists
    assert os.path.exists(absolute_workflow_workspace)
    _delete_workflow(workflow,
                     hard_delete=hard_delete,
                     workspace=workspace)
    if hard_delete or workspace:
        assert not os.path.exists(absolute_workflow_workspace)

    # check that all cache entries for jobs
    # of the deleted workflow are removed
    cache_entries_after_delete = JobCache.query.filter_by(
        job_id=workflow_job.id_).all()
    assert not cache_entries_after_delete


def test_deletion_of_workspace_of_an_already_deleted_workflow(
        app,
        session,
        default_user,
        sample_yadage_workflow_in_db,
        tmp_shared_volume_path):
    """Test workspace deletion of an already deleted workflow."""
    create_workflow_workspace(sample_yadage_workflow_in_db.get_workspace())
    absolute_workflow_workspace = os.path.join(
        tmp_shared_volume_path,
        sample_yadage_workflow_in_db.get_workspace())

    # check that the workflow workspace exists
    assert os.path.exists(absolute_workflow_workspace)
    _delete_workflow(sample_yadage_workflow_in_db,
                     hard_delete=False,
                     workspace=False)
    assert os.path.exists(absolute_workflow_workspace)

    _delete_workflow(sample_yadage_workflow_in_db,
                     hard_delete=False,
                     workspace=True)
    assert not os.path.exists(absolute_workflow_workspace)

    _delete_workflow(sample_yadage_workflow_in_db,
                     hard_delete=True,
                     workspace=True)
