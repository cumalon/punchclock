from timeclock.database import init_database, create_terminal_event

init_database()
create_terminal_event("startup", "Terminal iniciat")
