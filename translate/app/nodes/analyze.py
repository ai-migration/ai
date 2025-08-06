from analyzer.python_analyzer import PythonAnalyzer
from analyzer.java_analyzer import JavaAnalyzer
from analyzer.structure_mapper import StructureMapper
from analyzer.xml_mapper_analyzer import XmlMapperAnalyzer


def analyze_python(state: State) -> State:
    """
    Python 소스 파일을 분석하여 클래스 및 함수 정보와 역할을 추출합니다.

    전처리 단계에서 식별된 ``code_files`` 중 Python 파일을 순회하며,
    ``PythonAnalyzer``로 파싱하고, ``StructureMapper``로 역할(controller, service, dao 등)을 추론합니다.
    추출된 클래스 정보는 ``state['classes']``, 함수 정보는 ``state['functions']``에 저장됩니다.
    """
    code_files = state.get('code_files') or []
    functions: list = []
    classes: list = []
    base_zip = os.path.basename(state.get('input_zip') or '')
    mapper = StructureMapper()

    for file_path, lang in code_files:
        if lang != 'python':
            continue
        analyzer = PythonAnalyzer(file_path)
        if not analyzer.is_parsed:
            continue
        # Extract class and function information
        file_classes = analyzer.extract_classes()
        file_functions = analyzer.extract_functions()

        # Annotate classes with source info and role
        for cls in file_classes:
            source_info = {
                'zip_file': base_zip,
                'rel_path': os.path.relpath(file_path, state.get('extract_dir', '')),
                'language': 'python'
            }
            cls['source_info'] = source_info
            # gather functions belonging to this class for role inference
            class_funcs = [f for f in file_functions if f.get('class') == cls['name']]
            role_info = mapper.infer_class_role({**cls, 'functions': class_funcs})
            cls['role'] = role_info
            classes.append(cls)

        # Annotate functions with source info and role for standalone functions
        for func in file_functions:
            source_info = {
                'zip_file': base_zip,
                'rel_path': os.path.relpath(file_path, state.get('extract_dir', '')),
                'language': 'python'
            }
            func['source_info'] = source_info
            if not func.get('class'):
                # stand-alone function: infer role
                role_info = mapper.infer_standalone_function_role(func)
                func['role'] = role_info
            functions.append(func)

    state['classes'] = classes
    state['functions'] = functions
    return state


def analyze_java(state: State) -> State:
    """
    Java 소스 파일을 분석하여 클래스의 역할을 추출하고 feature 단위로 그룹화합니다.

    1. ``src/main/resources`` 경로에서 XML Mapper 파일을 분석해 SQL 쿼리를 추출합니다.
    2. Java 파일을 ``JavaAnalyzer``로 파싱하고 ``StructureMapper``로 역할을 추론합니다.
    3. 클래스 이름을 기반으로 feature 이름을 도출하고, 역할별로 파일을 그룹화합니다.
    4. 최종 결과는 ``state['java_analysis']``에 저장됩니다.
    """
    code_files = state.get('code_files') or []
    base_zip = os.path.basename(state.get('input_zip') or '')
    extract_dir = state.get('extract_dir', '')

    # Build query bank from XML mapper files (for SQL queries)
    query_bank: dict = {}
    for file_path, lang in code_files:
        if lang == 'xml' and 'src/main/resources' in file_path:
            xml_analyzer = XmlMapperAnalyzer(file_path)
            query_bank.update(xml_analyzer.get_queries())

    classes: list = []
    mapper = StructureMapper()

    # Analyze each Java source file
    for file_path, lang in code_files:
        if lang != 'java':
            continue
        analyzer = JavaAnalyzer(file_path, query_bank=query_bank)
        if not analyzer.is_parsed:
            continue
        file_classes = analyzer.extract_classes()
        rel_path = os.path.relpath(file_path, extract_dir)
        for cls in file_classes:
            source_info = {
                'zip_file': base_zip,
                'rel_path': rel_path,
                'language': 'java'
            }
            cls['source_info'] = source_info
            # Role inference for Java classes (no functions required)
            role_info = mapper.infer_class_role(cls)
            cls['role'] = role_info
            classes.append(cls)

    # Derive feature names and group classes by feature
    classes_with_feature = []
    for cls in classes:
        class_name = cls.get('name', '')
        feature = 'unknown'
        match = re.search(r'^(.*?)(Controller|Service|ServiceImpl|Repository|DAO|VO|Dto|Entity|Config|Exception|Util|Filter|Jwt|Impl|Tests|Test)$', class_name, re.IGNORECASE)
        if match:
            feature_candidate = match.group(1)
            # remove leading Res/Req prefixes
            feature_candidate = re.sub(r'^(Res|Req)', '', feature_candidate, flags=re.IGNORECASE)
            feature = feature_candidate.lower() if feature_candidate else class_name.lower()
        else:
            feature = class_name.lower()
        if class_name.endswith('Application'):
            feature = 'app'
        cls['feature'] = feature
        classes_with_feature.append(cls)

    classes_by_feature: dict = {}
    for cls in classes_with_feature:
        feature = cls['feature']
        classes_by_feature.setdefault(feature, []).append(cls)

    # Build the final analysis structure similar to run_pipeline
    output_list: list = []
    for feature, cls_list in classes_by_feature.items():
        feature_set: dict = {}
        for cls in cls_list:
            role = cls.get('role', {}).get('type', '').lower()
            path = cls.get('source_info', {}).get('rel_path', '')
            # unify service and service_impl under 'service'
            if role == 'serviceimpl':
                role = 'service'
            # initialize list for role
            feature_set.setdefault(role, []).append(path)
        if feature_set:
            output_list.append(feature_set)

    state['java_analysis'] = output_list
    return state

