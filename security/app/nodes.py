from state import State

def test_node(state: State):
    print(state)
    return {'message': '요청 완료'}

def preprocessing():
    pass

def analyze_security():
    pass

def has_vulnerability():
    pass

def retrieve():
    pass

def recommend_security_solution():
    pass

def report():
    pass

def check_vulnerability():
    # 취약점이 있는 경우 rag, 없는 경우 report 노드로 이동하도록 return 수정
    return 'rag'