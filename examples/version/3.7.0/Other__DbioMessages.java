/*
 * Copyright 2008-2009 the original author or authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package egovframework.dev.imp.dbio.common;

import org.eclipse.osgi.util.NLS;

/**
 * 다국어 처리를 위한 메시지 클래스
 * @author 개발환경 개발팀 김형조
 * @since 2009.02.20
 * @version 1.0
 * @see
 *
 * <pre>
 * << 개정이력(Modification Information) >>
 *   
 *   수정일      수정자           수정내용
 *  -------    --------    ---------------------------
 *   2009.02.20  김형조          최초 생성
 *
 * 
 * </pre>
 */
public class DbioMessages extends NLS {

	/** 번들명 */
	private static final String BUNDLE_NAME = "egovframework.dev.imp.dbio.common.messages"; //$NON-NLS-1$
	public static String NewSqlMapConfigWizardPage_1;
	public static String NewSqlMapConfigWizardPage_2;
	public static String NewSqlMapWizardPage_1;
	public static String NewSqlMapWizardPage_2;
	/** SQL MAP 에서 쿼리 ID 중복 체크 오류 메시지 */	
	public static String sqlmap_err_QueryId_duplication;
	/** SQL MAP 에서 ParameterMap ID 중복 체크 오류 메시지 */
	public static String sqlmap_err_ParameterMapId_duplication;
	/** SQL MAP 에서 ResultMap ID 중복 체크 오류 메시지 */
	public static String sqlmap_err_ResultMapId_duplication;
	/** SQL MAP 에서 Alias ID 중복 체크 오류 메시지 */
	public static String sqlmap_err_AliasName_duplication;
	/** SQL MAP 에서 쿼리 ID 공백 오류 메시지 */	
	public static String sqlmap_err_QueryId_invalid;
	/** SQL MAP 에서 ParameterMap ID 공백 오류 메시지 */
	public static String sqlmap_err_ParameterMapId_invalid;
	/** SQL MAP 에서 ResultMap ID 공백 오류 메시지 */
	public static String sqlmap_err_ResultMapId_invalid;
	/** SQL MAP 에서 Alias ID 공백 오류 메시지 */
	public static String sqlmap_err_AliasName_invalid;
	/** 바인딩 변수 사용 오류 */
	public static String sqlmap_err_binding_variables;
	/** SQL MAP CONFIG 에서 Property Name 중복 오류 메시지 */
	public static String sqlmapconfig_err_PropertyName_duplication;
	/** SQL MAP CONFIG 에서 Property Name 공백 오류 메시지 */
	public static String sqlmapconfig_err_PropertyName_invalid;
	/** SQL MAP CONFIG 에서 Property Value 공백 오류 메시지 */
	public static String sqlmapconfig_err_PropertyValue_empty;	
	/**	SQL MAP 에서 VO 생성시 테스트를 먼저 수행하라는 메시지 */
	public static String sqlmap_info_doQueryTest;
	/**	SQL 쿼리 테스터에서 select 결과행이 없을 경우 메시지 */
	public static String query_result_zero_info;	
	/** 컨텐트 */
	
	/** 리소스 번들 초기화 */
	static {
		NLS.initializeMessages(BUNDLE_NAME, DbioMessages.class);
	}

}
