-- SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
--
-- SPDX-License-Identifier: Apache-2.0
--
-- Kumoss core schema. Equivalent to what SQLAlchemy's metadata.create_all
-- produced for the Python core, so existing databases are used as they
-- are: enum types store the Python enum *names*, ids are SERIAL, and only
-- missing objects are created (nothing is ever altered or dropped).

DO $$ BEGIN
    CREATE TYPE gitprovidername AS ENUM ('GITHUB', 'AZURE_DEVOPS', 'GITLAB');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE operationrole AS ENUM ('DEVELOPER', 'DEVOPS');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE operationtype AS ENUM ('GENERATE', 'DRIFT', 'IMPORT');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE panelrole AS ENUM ('VIEWER', 'EDITOR', 'ADMIN');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE reporttype AS ENUM ('GENERATE', 'DRIFT', 'IMPORT', 'APPLY');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE sessionstatus AS ENUM (
        'STARTED', 'FILTERING', 'GENERATING', 'VALIDATING', 'RECONCILING',
        'REPORT', 'APPLY', 'COMPLETED', 'UNCOMPLETED', 'FAILED'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE terraformprovider AS ENUM ('AZURE', 'GCP', 'AWS', 'OCI', 'K8S', 'VMWARE');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS artifacts (
    uri TEXT NOT NULL,
    content_type VARCHAR(64) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS users (
    issuer VARCHAR(512) NOT NULL,
    subject VARCHAR(254) NOT NULL,
    email VARCHAR(254),
    display_name VARCHAR(254),
    operation_role operationrole NOT NULL,
    panel_role panelrole,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (issuer, subject)
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS sessions (
    uuid UUID NOT NULL,
    user_id INTEGER NOT NULL,
    operation operationtype NOT NULL,
    in_flight BOOLEAN NOT NULL,
    is_blocked BOOLEAN NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_sessions_uuid ON sessions (uuid);

CREATE TABLE IF NOT EXISTS histories (
    session_id INTEGER NOT NULL,
    first_query TEXT NOT NULL,
    payload JSON NOT NULL,
    chat_payload JSON NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
CREATE INDEX IF NOT EXISTS ix_histories_session_id ON histories (session_id);

CREATE TABLE IF NOT EXISTS rounds (
    session_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    query TEXT NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (session_id, number),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
CREATE INDEX IF NOT EXISTS ix_rounds_session_id ON rounds (session_id);

CREATE TABLE IF NOT EXISTS terraform_providers (
    session_id INTEGER NOT NULL,
    provider terraformprovider NOT NULL,
    scope_id VARCHAR(1016) NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
CREATE INDEX IF NOT EXISTS ix_terraform_providers_session_id ON terraform_providers (session_id);

CREATE TABLE IF NOT EXISTS workspaces (
    session_id INTEGER NOT NULL,
    uri TEXT NOT NULL,
    branch VARCHAR(254) NOT NULL,
    root_path TEXT NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
CREATE INDEX IF NOT EXISTS ix_workspaces_session_id ON workspaces (session_id);

CREATE TABLE IF NOT EXISTS code_changes (
    round_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    file_name VARCHAR(254) NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts (id)
);
CREATE INDEX IF NOT EXISTS ix_code_changes_artifact_id ON code_changes (artifact_id);
CREATE INDEX IF NOT EXISTS ix_code_changes_round_id ON code_changes (round_id);

CREATE TABLE IF NOT EXISTS compliance_checks (
    round_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    passed BOOLEAN NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts (id)
);
CREATE INDEX IF NOT EXISTS ix_compliance_checks_artifact_id ON compliance_checks (artifact_id);
CREATE INDEX IF NOT EXISTS ix_compliance_checks_round_id ON compliance_checks (round_id);

CREATE TABLE IF NOT EXISTS pull_requests (
    round_id INTEGER NOT NULL,
    provider gitprovidername NOT NULL,
    number INTEGER NOT NULL,
    url VARCHAR(254) NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id)
);
CREATE INDEX IF NOT EXISTS ix_pull_requests_round_id ON pull_requests (round_id);

CREATE TABLE IF NOT EXISTS reports (
    round_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    type reporttype NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts (id)
);
CREATE INDEX IF NOT EXISTS ix_reports_artifact_id ON reports (artifact_id);
CREATE INDEX IF NOT EXISTS ix_reports_round_id ON reports (round_id);

CREATE TABLE IF NOT EXISTS statuses (
    session_id INTEGER NOT NULL,
    round_id INTEGER NOT NULL,
    status sessionstatus NOT NULL,
    message TEXT NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (session_id) REFERENCES sessions (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id)
);
CREATE INDEX IF NOT EXISTS ix_statuses_round_id ON statuses (round_id);
CREATE INDEX IF NOT EXISTS ix_statuses_session_id ON statuses (session_id);

CREATE TABLE IF NOT EXISTS terraform_plans (
    round_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    targets VARCHAR[] NOT NULL,
    id SERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (round_id) REFERENCES rounds (id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts (id)
);
CREATE INDEX IF NOT EXISTS ix_terraform_plans_artifact_id ON terraform_plans (artifact_id);
CREATE INDEX IF NOT EXISTS ix_terraform_plans_round_id ON terraform_plans (round_id);
