from crewai import Agent, Task, Crew
from analyze_agent import analyze_crew
from egov_agent import egov_crew
import os

os.environ['OPENAI_API_KEY'] = ''

if __name__ == '__main__':
    import tempfile
    import json
    input_zip_path = r'C:\Users\User\Desktop\dev\project\0811test.zip'  

    with tempfile.TemporaryDirectory() as temp_dir_path:
        initial_state = {"user_id": 1, "job_id": 100,  "input_path": input_zip_path, "extract_dir": temp_dir_path}

        # result = analyze_crew.kickoff(inputs={"state": initial_state})

    ######################## TO-BE: 전처리 코드 만들어서 analyze_result를 실제 입력 포맷으로 만들기 ########################
    # analyze_result = result.tasks_output[-1].pydantic.model_dump()
    # print(type(analyze_result))
    # print(analyze_result)
    ####################### EGOV CONVERSION TEST #######################
    input = {'controller': [r'C:\Users\User\Desktop\dev\project\BoardController.java'],
            'serviceimpl': [],
            # 'serviceimpl': [r'C:\Users\User\Desktop\dev\project\BoardService.java'],
            'service': [],
            'vo': []}
            # 'vo': [r'C:\Users\User\Desktop\dev\project\BoardUpdateDto.java']}
    
    initial_state = {
        'user_id': 1,
        'job_id': 100,
        'controller': [],
        'service': [],
        'serviceimpl': [],  
        'vo': [],

        'controller_egov': [],
        'service_egov': [],
        'serviceimpl_egov': [],
        'vo_egov': [],

        'input_path': {},
        'controller_report': {},
        'service_report': {},
        'serviceimpl_report': {},
        'vo_report': {},
        'retrieved': [],
        'validate': '',
        'next_role': '',
        'next_step': ''
    }

    for role, paths in input.items():
        for p in paths:
            with open(p, encoding='utf-8') as f:
                code = f.read()
                initial_state[role].append(code)

    result = egov_crew.kickoff(inputs={"state": initial_state})
