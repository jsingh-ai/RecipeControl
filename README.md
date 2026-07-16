# RecipeControl

RecipeControl is a historical, single-user application for building immutable time-based break definitions over minute-bucketed OPC UA samples, generating complete timelines, and labeling segments. It writes only to its own application database. It never writes to PLCs or collector-owned tables.

This repository is designed to run natively on a Windows VM without a container runtime or separate web server.

## Security boundary

RecipeControl does not have user authentication. Keep TCP port 8000 behind a trusted LAN, VPN, Windows Firewall rule, authenticated reverse proxy, or SSH tunnel. Do not expose it directly to the public internet.

Use two different MySQL accounts:

- A writable account limited to the separate RecipeControl application database.
- A SELECT-only account limited to the existing collector database.

Never point APP_DATABASE_URL at opcua_collector. Never give the application source account write privileges.

## What runs on the Windows VM

The native deployment has three components:

1. MySQL 8.0 or newer, installed on the VM or reachable over the network.
2. One FastAPI process that serves both the production React application and /api.
3. One historical worker process that handles queued analyses.

The React development server is not used in production. Node.js is needed during installation and updates to build frontend/dist, after which FastAPI serves those static files on the same port as the API.

Live mode remains disabled. Do not start recipecontrol.live_worker.

## Windows VM deployment: step by step

### 1. Install prerequisites

Install these 64-bit applications:

- Git for Windows
- Python 3.12, including the Python Launcher
- Node.js 20 LTS, including npm
- MySQL Server 8.0 or newer, unless application MySQL is on another server
- MySQL command-line tools for backup and restore

Open a new PowerShell window and verify:

    git --version
    py -3.12 --version
    node --version
    npm --version
    mysql --version

If PowerShell blocks local scripts, an administrator can allow locally created scripts for the current user:

    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

Do not use an unrestricted machine-wide execution policy.

### 2. Clone the repository

Choose a stable application directory. The service account must be able to read this directory and write its logs directory.

    cd C:\
    git clone <repository-url> RecipeControl
    cd C:\RecipeControl

If the repository already exists:

    cd C:\RecipeControl
    git branch --show-current
    git status --short
    git pull

Do not pull over uncommitted production changes. Secrets belong only in the ignored .env file.

### 3. Create the RecipeControl application database

RecipeControl must use a database separate from opcua_collector. Open MySQL as an administrator:

    mysql -u root -p

Run the following SQL after replacing the example password:

    CREATE DATABASE recipecontrol
      CHARACTER SET utf8mb4
      COLLATE utf8mb4_unicode_ci;

    CREATE USER 'recipecontrol_app'@'127.0.0.1'
      IDENTIFIED BY 'replace_with_a_strong_password';

    GRANT ALL PRIVILEGES ON recipecontrol.*
      TO 'recipecontrol_app'@'127.0.0.1';

    FLUSH PRIVILEGES;
    EXIT;

If MySQL runs on another host, the database administrator must create a narrowly scoped account for the Windows VM rather than using root. APP_DATABASE_URL will use that host instead of 127.0.0.1.

The application creates tables only after you explicitly run Alembic in step 7. Normal startup does not create the database.

### 4. Create or verify the read-only collector account

The collector administrator should create a separate SELECT-only account. A same-host example is:

    CREATE USER 'recipecontrol_reader'@'127.0.0.1'
      IDENTIFIED BY 'replace_with_another_strong_password';

    GRANT SELECT ON opcua_collector.*
      TO 'recipecontrol_reader'@'127.0.0.1';

    FLUSH PRIVILEGES;

Connect as that account and verify:

    SELECT CURRENT_USER();
    SHOW GRANTS FOR CURRENT_USER;

It must not have INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, or other write privileges on collector tables.

### 5. Install Python and frontend dependencies

From an ordinary PowerShell window:

    cd C:\RecipeControl
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Install-RecipeControl.ps1

The script performs only local installation and build operations:

- creates .venv with Python 3.12
- installs RecipeControl
- runs npm ci
- runs npm run build
- creates local logs and backups directories
- copies .env.windows.example to .env if .env does not exist

It does not connect to MySQL, run migrations, query the collector, or start the application.

### 6. Configure the environment

Open the generated file:

    notepad .env

At minimum, set APP_DATABASE_URL, SOURCE_DATABASE_URL, and CORS_ORIGINS.

Application MySQL on this Windows VM:

    APP_DATABASE_URL=mysql+pymysql://recipecontrol_app:url_encoded_password@127.0.0.1:3306/recipecontrol

Collector MySQL on this Windows VM:

    SOURCE_DATABASE_URL=mysql+pymysql://recipecontrol_reader:url_encoded_password@127.0.0.1:3306/opcua_collector

Collector MySQL on another network host:

    SOURCE_DATABASE_URL=mysql+pymysql://recipecontrol_reader:url_encoded_password@10.20.30.40:3306/opcua_collector

On native Windows, 127.0.0.1 correctly means the Windows VM. Make sure remote MySQL and Windows Firewall rules allow only the necessary hosts.

Percent-encode special password characters in database URLs. For example, @ becomes %40 and # becomes %23. Do not commit or email .env.

Keep these production values:

    SOURCE_ADAPTER=mysql
    SERVE_FRONTEND=true
    FRONTEND_DIST_PATH=frontend/dist
    ENABLE_LIVE_MODE=false
    VITE_API_URL=/api
    VITE_ENABLE_LIVE_MODE=false

If operators browse to http://recipecontrol-vm:8000, use:

    CORS_ORIGINS=http://recipecontrol-vm:8000

### 7. Run application-database migrations

This command connects only to APP_DATABASE_URL and creates or upgrades RecipeControl-owned tables:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Invoke-Migrations.ps1

It does not create, alter, or drop collector-owned tables.

### 8. Synchronize the local machine catalog

Run the source diagnostics first:

    .\.venv\Scripts\python.exe -m recipecontrol.source_smoke health
    .\.venv\Scripts\python.exe -m recipecontrol.source_smoke diagnostics

These commands issue read-only source queries and do not print connection URLs or credentials.

Synchronize enabled source machines into the RecipeControl application database:

    .\.venv\Scripts\python.exe -m recipecontrol.seed

This reads source machines and writes only the local RecipeControl machine catalog. The application also refreshes the catalog when the machine list is opened.

### 9. Test the API manually

Open PowerShell window 1:

    cd C:\RecipeControl
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Start-Api.ps1 -Console

Open PowerShell window 2 and check health:

    Invoke-RestMethod http://127.0.0.1:8000/health
    Invoke-RestMethod http://127.0.0.1:8000/api/health

Open http://127.0.0.1:8000/ on the VM. Press Ctrl+C in window 1 after the test.

### 10. Test the historical worker manually

Open PowerShell window 2:

    cd C:\RecipeControl
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Start-Worker.ps1 -Console

Leave both API and worker windows open, then create a small historical analysis in the browser. It should move from QUEUED to COMPLETE. Press Ctrl+C in both windows after testing.

### 11. Open the firewall only for the protected network

Run PowerShell as an administrator and replace the example subnet:

    New-NetFirewallRule -DisplayName "RecipeControl protected web access" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress 10.20.0.0/16 -Action Allow

Do not create an Any/Internet inbound rule. Operators can then open:

    http://<windows-vm-name-or-ip>:8000/

### 12. Configure automatic startup with Task Scheduler

Use a dedicated, non-administrator Windows service account that has read/execute access to C:\RecipeControl, write access to C:\RecipeControl\logs, network access to both MySQL servers, and Log on as a batch job permission.

Create two tasks in Task Scheduler.

For the API task:

1. Select **Create Task**, not Create Basic Task.
2. Name it **RecipeControl API**.
3. Select **Run whether user is logged on or not**.
4. Use the dedicated non-administrator account.
5. Add an **At startup** trigger with a 30-second delay.
6. Add a **Start a program** action with Program set to powershell.exe.
7. Set Arguments to:

       -NoProfile -ExecutionPolicy Bypass -File C:\RecipeControl\scripts\windows\Start-Api.ps1

8. Set Start in to C:\RecipeControl.
9. Enable restart every 1 minute after failure and allow at least 3 attempts.
10. Set **If the task is already running** to **Do not start a new instance**.

Create **RecipeControl Historical Worker** with the same settings, but use:

    -NoProfile -ExecutionPolicy Bypass -File C:\RecipeControl\scripts\windows\Start-Worker.ps1

Do not create a live-worker task.

Start and inspect the tasks:

    Start-ScheduledTask -TaskName "RecipeControl API"
    Start-ScheduledTask -TaskName "RecipeControl Historical Worker"
    Get-ScheduledTask -TaskName "RecipeControl*"
    Get-ScheduledTaskInfo -TaskName "RecipeControl API"
    Get-ScheduledTaskInfo -TaskName "RecipeControl Historical Worker"

### 13. Check logs and health

    Get-Content C:\RecipeControl\logs\api.log -Tail 100
    Get-Content C:\RecipeControl\logs\worker.log -Tail 100
    Get-Content C:\RecipeControl\logs\worker.log -Wait
    Invoke-RestMethod http://127.0.0.1:8000/health
    Invoke-RestMethod http://127.0.0.1:8000/api/health

### 14. Create the first real historical analysis

1. Open RecipeControl from the protected network.
2. Open **Rule Builder** and select the machine.
3. Create a rule set and draft version.
4. Search for tags and add the required conditions and groups.
5. Save the draft and lock it.
6. Open **Timeline** and choose the same machine and locked version.
7. Enter a UTC start minute and inclusive UTC end minute.
8. Select **Analyze**.
9. Wait for the historical worker to mark it COMPLETE.
10. Inspect primary and condition lanes, then annotate a segment.

The same source tag may be used in multiple conditions. Conditions remain distinct by their condition IDs.

### 15. Back up the RecipeControl database

This prompts for the application password and avoids placing it in command history:

    cd C:\RecipeControl
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    mysqldump.exe --host=127.0.0.1 --user=recipecontrol_app --password --single-transaction --routines --triggers --result-file="backups\recipecontrol-$Stamp.sql" recipecontrol

Backups contain RecipeControl definitions, analyses, minute snapshots, and annotations. They do not contain collector tables.

### 16. Restore the RecipeControl database

Test restores on an isolated system first. Stop both tasks, verify the target is recipecontrol rather than opcua_collector, restore, migrate, and restart:

    Stop-ScheduledTask -TaskName "RecipeControl API"
    Stop-ScheduledTask -TaskName "RecipeControl Historical Worker"
    cmd.exe /c "mysql.exe --host=127.0.0.1 --user=recipecontrol_app --password recipecontrol < backups\selected-backup.sql"
    .\scripts\windows\Invoke-Migrations.ps1
    Start-ScheduledTask -TaskName "RecipeControl API"
    Start-ScheduledTask -TaskName "RecipeControl Historical Worker"
    Invoke-RestMethod http://127.0.0.1:8000/api/health

### 17. Pull and deploy updates safely

Back up first, then:

    cd C:\RecipeControl
    Stop-ScheduledTask -TaskName "RecipeControl API"
    Stop-ScheduledTask -TaskName "RecipeControl Historical Worker"
    git branch --show-current
    git status --short
    git pull
    .\scripts\windows\Install-RecipeControl.ps1
    .\scripts\windows\Invoke-Migrations.ps1
    Start-ScheduledTask -TaskName "RecipeControl API"
    Start-ScheduledTask -TaskName "RecipeControl Historical Worker"
    Invoke-RestMethod http://127.0.0.1:8000/api/health
    Get-Content .\logs\api.log -Tail 100
    Get-Content .\logs\worker.log -Tail 100

### 18. Safe restart and shutdown

Restart:

    Stop-ScheduledTask -TaskName "RecipeControl API"
    Stop-ScheduledTask -TaskName "RecipeControl Historical Worker"
    Start-ScheduledTask -TaskName "RecipeControl API"
    Start-ScheduledTask -TaskName "RecipeControl Historical Worker"

Stop:

    Stop-ScheduledTask -TaskName "RecipeControl API"
    Stop-ScheduledTask -TaskName "RecipeControl Historical Worker"

Stopping RecipeControl does not stop MySQL and does not delete data.

## Local fixture development

The deterministic fixture requires no collector connection:

    Copy-Item .env.example .env
    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    cd frontend
    npm ci
    cd ..
    .\.venv\Scripts\python.exe -m alembic upgrade head
    .\.venv\Scripts\python.exe -m recipecontrol.seed

Keep SOURCE_ADAPTER=fixture, SERVE_FRONTEND=false, and APP_DATABASE_URL=sqlite:///./recipecontrol.db.

Run three PowerShell windows:

    .\.venv\Scripts\python.exe -m uvicorn recipecontrol.api:app --reload --host 127.0.0.1 --port 8000

    .\.venv\Scripts\python.exe -m recipecontrol.worker

    cd frontend
    npm run dev

Open http://127.0.0.1:5173.

## Verification commands

    .\.venv\Scripts\ruff.exe format --check backend
    .\.venv\Scripts\ruff.exe check backend
    .\.venv\Scripts\mypy.exe backend\recipecontrol
    .\.venv\Scripts\pytest.exe backend\tests
    cd frontend
    npm test
    npm run lint
    npm run typecheck
    npm run build

Optional real MySQL tests require two isolated test databases supplied through TEST_COLLECTOR_MYSQL_URL and TEST_APP_MYSQL_URL. Never point them at production:

    $env:TEST_COLLECTOR_MYSQL_URL = "mysql+pymysql://test_user:url_encoded_password@127.0.0.1:3306/opcua_collector_test"
    $env:TEST_APP_MYSQL_URL = "mysql+pymysql://test_user:url_encoded_password@127.0.0.1:3306/recipecontrol_test"
    .\.venv\Scripts\pytest.exe backend\tests\test_mysql_integration.py backend\tests\test_migrations.py backend\mysql_tests\test_app_mysql_workflow.py

## Troubleshooting

- **Frontend build missing:** run Install-RecipeControl.ps1.
- **No application tables:** run Invoke-Migrations.ps1 using the same .env as API and worker.
- **Analysis remains queued:** start the historical worker and inspect logs\worker.log.
- **Source unavailable:** verify the SELECT-only URL, MySQL listener, firewall, and account host grant.
- **Access denied:** URL-encode the password and verify the application and source credentials were not swapped.
- **Port 8000 already in use:** stop the conflict or consistently choose another API port and firewall rule.
- **Inactive machine:** historical analyses remain viewable; new definitions and analyses require an enabled machine.

## Safety notes

- Collector tables are read-only and are never migrated by RecipeControl.
- Application and source URLs must use separate credentials and databases.
- Database timestamps are UTC.
- Selected end minutes are inclusive; engine and persistence intervals are half-open.
- Locked versions and generated historical boundaries are immutable through public APIs.
- ENABLE_LIVE_MODE=false is the supported default.
- RecipeControl has no built-in authentication.

See [Windows VM deployment](docs/windows-vm-deployment.md), [architecture](docs/architecture.md), [segmentation](docs/segmentation-algorithm.md), [source mapping](docs/source-schema.md), [data model](docs/data-model.md), and [live-mode limitations](docs/live-mode.md).
