# Marximus-Finance
A modular, metadata-driven CRM-style web application built for Finance.
Major credit design to [SuiteCRM](https://docs.suitecrm.com/developer/database-schema/)

## Overview
This is a personal finance web application built using Python, Flask, SQLAlchemy, psycopg3, and PostgreSQL. The application follows a modular architecture with metadata-driven entity definitions.

## Project Structure

```
/app
  /core              - Core engine components
    metadata_engine.py  - Handles metadata-driven CRM entity definitions
    module_loader.py    - Dynamically loads CRM modules
    schema_sync.py      - Synchronizes database schema with metadata
    crud_engine.py      - Provides generic CRUD operations
  /modules           - Custom CRM modules (empty, ready for extensions)
  /api               - API layer
    routes.py          - Flask API routes
  /db                - Database layer
    base.py            - SQLAlchemy base configuration
    session.py         - Database session management
  /utils             - Utility functions (empty, ready for helpers)
/config              - Configuration files
/tests               - Test suite
```

## Technologies

- **Python 3.11** - Core programming language
- **Flask 3.0** - Web framework
- **SQLAlchemy 2.0** - ORM
- **psycopg3** - PostgreSQL adapter
- **PostgreSQL 16** - Database
- **Docker & Docker Compose** - Containerization

## Getting Started

### Prerequisites
- Docker
- Docker Compose

### Running the Application

1. Build and start the containers:
```bash
docker-compose up --build
```

2. The application will be available at:
   - Web App: http://localhost:5000
   - PostgreSQL: localhost:5432

### Database Connection

The application connects to PostgreSQL with the following credentials:
- Database: `marximus_crm`
- User: `marximus`
- Password: `marximus_password`
- Host: `db` (within Docker network: `marximus_network`)

### Development

The application is configured for development mode with:
- Hot-reload enabled
- Debug mode on
- Volume mounting for live code updates

## Architecture

This application uses a metadata-driven architecture where:
1. Entities are defined through metadata
2. Database schema is synchronized automatically
3. CRUD operations are generated dynamically
4. Modules can be loaded and extended at runtime

## Next Steps

- Implement metadata engine for entity definitions
- Create schema synchronization logic
- Build CRUD engine for dynamic operations
- Add custom modules for specific CRM features
- Develop API routes for frontend integration
