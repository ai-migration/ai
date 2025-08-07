# app/nodes/analyze.py
import os, re, json, logging
from app.states import State
from analyzer.python_analyzer import PythonAnalyzer
from analyzer.java_analyzer import JavaAnalyzer
from analyzer.xml_mapper_analyzer import XmlMapperAnalyzer
from analyzer.structure_mapper import StructureMapper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def analyze(state: State) -> State:
    lang = state.get('language')
    if lang == 'python':
        return _analyze_python(state)
    elif lang == 'java':
        return _analyze_java(state)
    return state

def _analyze_python(state: State) -> State:
    logging.info("Analyzing Python project...")
    all_classes, all_functions = [], []
    mapper = StructureMapper()
    
    for file_path, lang in state.get('code_files', []):
        if lang != 'python': continue
        
        rel_path = os.path.relpath(file_path, state.get('extract_dir'))
        source_info = {"zip_file": os.path.basename(state.get('input_path','')), "rel_path": rel_path, "language": lang}
        
        analyzer = PythonAnalyzer(file_path)
        if not analyzer.is_parsed: continue
        
        py_funcs = analyzer.extract_functions()
        py_classes = analyzer.extract_classes()

        for func in py_funcs:
            func['source_info'] = source_info
            if not func.get('class'):
                func['role'] = mapper.infer_standalone_function_role(func)
            all_functions.append(func)

        for cls in py_classes:
            cls['source_info'] = source_info
            class_methods = [f for f in py_funcs if f.get('class') == cls.get('name')]
            cls['role'] = mapper.infer_class_role({**cls, "functions": class_methods})
            all_classes.append(cls)

    state['classes'], state['functions'] = all_classes, all_functions
    logging.info(f"Python analysis complete: {len(all_classes)} classes, {len(all_functions)} functions.")
    return state

def _analyze_java(state: State) -> State:
    logging.info("Analyzing Java project...")
    all_classes, all_functions, query_bank = [], [], {}
    mapper = StructureMapper()

    for file_path, lang in state.get('code_files', []):
        if lang == 'xml' and 'src/main/resources' in file_path:
            query_bank.update(XmlMapperAnalyzer(file_path).get_queries())

    for file_path, lang in state.get('code_files', []):
        if lang != 'java': continue
        
        rel_path = os.path.relpath(file_path, state.get('extract_dir'))
        source_info = {"zip_file": os.path.basename(state.get('input_path','')), "rel_path": rel_path, "language": lang}
        
        analyzer = JavaAnalyzer(file_path, query_bank)
        if not analyzer.is_parsed: continue

        for cls in analyzer.extract_classes():
            cls['source_info'] = source_info
            cls['role'] = mapper.infer_class_role(cls)
            all_classes.append(cls)
        
        for func in analyzer.extract_functions():
            func['source_info'] = source_info
            all_functions.append(func)
    
    # Feature 그룹화 (run_pipeline.py 로직)
    classes_by_feature = {}
    for cls in all_classes:
        class_name = cls.get("name", "")
        match = re.search(r'^(.*?)(Controller|Service|ServiceImpl|Repository|DAO|VO|Dto|Entity|Config|Exception|Util|Filter|Jwt|Impl|Tests|Test)$', class_name, re.IGNORECASE)
        feature = (match.group(1).lower() if match and match.group(1) else class_name.lower()) if not class_name.endswith("Application") else "app"
        cls['feature'] = feature
        classes_by_feature.setdefault(feature, []).append(cls)

    output_list = []
    for feature, classes in classes_by_feature.items():
        feature_set = {}
        for cls in classes:
            role = cls.get('role', {}).get('type', 'unknown').lower()
            if role == 'serviceimpl': role = 'service'
            feature_set.setdefault(role, []).append(cls.get('source_info',{}).get('rel_path'))
        if feature_set: output_list.append({feature: feature_set})
    
    state['classes'], state['functions'], state['java_analysis'] = all_classes, all_functions, output_list
    logging.info(f"Java analysis complete: {len(all_classes)} classes, grouped into {len(output_list)} features.")
    return state