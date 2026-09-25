from pipeline.schemas import ContractReference, ContractType
from pipeline.contract_resolver import ContractResolver

def test():
    resolver = ContractResolver()

    # --- TEST 1: URL Fetching ---
    print("Testing URL Resolution...")
    url_ref = ContractReference(
        type=ContractType.URL,
        location="http://localhost:8080/v3/api-docs/v1" 
    )
    try:
        # Note: If your local Spring Boot app isn't running, this will intentionally 
        # and correctly throw a RuntimeError thanks to our raise_for_status() logic.
        source_schema = resolver.resolve(url_ref)
        print(f"✅ URL Success! Found {len(source_schema.get('paths', {}))} paths.")
    except Exception as e:
        print(f"⚠️ URL Test Result (Expected if Spring Boot is down): {e}")

    # --- TEST 2: Raw Upload (YAML format) ---
    print("\nTesting UPLOAD Resolution (YAML)...")
    yaml_upload = """
openapi: 3.0.0
info:
  title: Mock Upload
paths:
  /api/test:
    get:
      operationId: getTest
    """
    upload_ref = ContractReference(
        type=ContractType.UPLOAD,
        content=yaml_upload
    )
    
    target_schema = resolver.resolve(upload_ref)
    print(f"✅ Upload Success! Found operation: {target_schema['paths']['/api/test']['get']['operationId']}")

if __name__ == "__main__":
    test()