from fastapi import FastAPI

app = FastAPI(title="Virtual Science Park API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
