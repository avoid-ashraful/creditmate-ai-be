# API documentation

The API reference is generated from the Django REST Framework views with
`drf-spectacular`.

## View the documentation locally

Run the backend with its normal environment and open:

- Swagger UI: `/api/v1/docs/swagger/`
- Redoc: `/api/v1/docs/redoc/`
- OpenAPI JSON: `/api/v1/schema/`

## Export and validate the schema

From the backend root, run:

```sh
python manage.py spectacular --file /tmp/schema.yml --validate
```

The command writes the OpenAPI document to the requested file and reports
schema validation issues in the terminal. In CI or a local test environment,
set the same Django database and service environment variables used by the
backend test suite before running it.
