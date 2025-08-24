0814 기준 테스트 방식 및 로직

api를 사용하려면 http://localhost:8084/agents/conversion 사용 -> 자세한 방식은 노션에 있음

- API로 테스트하는 방법
    http://localhost:8084/agents/conversion 사용 -> 자세한 방법은 노션에 있음
- 명령어로 실행하는 방법
    1. ai\orchestrate\app\main.py 실행
        - 에이전트 실행 끝난 후 완료 메세지를 받기 위함
    2. ~/ai 경로에서 ```python -m translate.app.orchestrator``` 실행

- 실행 결과
    - 명령어를 실행한 경로에 output 폴더가 생성됨
        생성되는 파일: java_analysis_results.json (언어가 자바인 경우)
                    conversion_result.json

### 추후 작업 사항
- 백엔드에서 output 경로 받아서 S3에 저장하고 output 폴더 삭제
- 맨 처음 경로 입력 시 S3에 있는 zip의 경로를 넘겨주고 그 경로에서 파일 읽기 (분석 에이전트에서)
- 리포트 자세하게