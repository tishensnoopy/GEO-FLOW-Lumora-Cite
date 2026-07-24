#!/bin/bash
# deploy/scripts/init-db.sh
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    CREATE TABLE IF NOT EXISTS article_distributions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        article_id VARCHAR(255) NOT NULL,
        client_id VARCHAR(64) NOT NULL,
        remote_url VARCHAR(512) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'synced',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_article_distributions_status ON article_distributions(status);
    CREATE INDEX idx_article_distributions_url ON article_distributions(remote_url);
    CREATE INDEX IF NOT EXISTS idx_article_distributions_client_id ON article_distributions(client_id);

    CREATE TABLE IF NOT EXISTS index_results (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL UNIQUE,
        client_id VARCHAR(64) NOT NULL,
        site_type VARCHAR(32) NOT NULL,
        content_title VARCHAR(512),
        content_keywords TEXT[],
        content_snapshot TEXT,
        baidu_status VARCHAR(32) DEFAULT 'pending',
        toutiao_status VARCHAR(32) DEFAULT 'pending',
        sogou_status VARCHAR(32) DEFAULT 'pending',
        so360_status VARCHAR(32) DEFAULT 'pending',
        bing_status VARCHAR(32) DEFAULT 'pending',
        baidu_checked_at TIMESTAMP,
        toutiao_checked_at TIMESTAMP,
        sogou_checked_at TIMESTAMP,
        so360_checked_at TIMESTAMP,
        bing_checked_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_index_results_client_id ON index_results(client_id);
    CREATE INDEX idx_index_results_site_type ON index_results(site_type);

    CREATE TABLE IF NOT EXISTS index_history (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL,
        check_date DATE NOT NULL,
        baidu_status VARCHAR(32) NOT NULL,
        toutiao_status VARCHAR(32) NOT NULL,
        sogou_status VARCHAR(32) NOT NULL,
        so360_status VARCHAR(32) NOT NULL,
        bing_status VARCHAR(32) NOT NULL,
        total_indexed INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(url, check_date)
    );
    CREATE INDEX idx_index_history_url ON index_history(url);
    CREATE INDEX idx_index_history_check_date ON index_history(check_date);

    CREATE TABLE IF NOT EXISTS citation_results (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL,
        model VARCHAR(64) NOT NULL,
        question TEXT NOT NULL,
        answer TEXT,
        hit_type VARCHAR(32) NOT NULL,
        sources JSONB,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(url, model, question)
    );
    CREATE INDEX idx_citation_results_url ON citation_results(url);
    CREATE INDEX idx_citation_results_model ON citation_results(model);

    CREATE TABLE IF NOT EXISTS clients (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        client_id VARCHAR(64) UNIQUE NOT NULL,
        username VARCHAR(128) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(255),
        phone VARCHAR(32),
        company_name VARCHAR(255),
        status VARCHAR(32) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS client_sites (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        client_id VARCHAR(64) NOT NULL,
        site_name VARCHAR(255) NOT NULL,
        domain VARCHAR(255) NOT NULL,
        site_type VARCHAR(32) NOT NULL,
        wordpress_api_url VARCHAR(512),
        wordpress_api_token VARCHAR(255),
        status VARCHAR(32) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(client_id, domain)
    );
    CREATE INDEX idx_client_sites_client_id ON client_sites(client_id);

    CREATE TABLE IF NOT EXISTS system_config (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        config_key VARCHAR(128) UNIQUE NOT NULL,
        config_value TEXT NOT NULL,
        config_type VARCHAR(32) NOT NULL,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
    ('index_scan_frequency', '1', 'number', '收录检测频率（天/次）'),
    ('index_scan_time', '02:00', 'string', '收录检测执行时间'),
    ('citation_scan_frequency', '7', 'number', 'AI 采信检测频率（天/次）'),
    ('citation_scan_time', '03:00', 'string', 'AI 采信检测执行时间'),
    ('citation_sample_size', '20', 'number', 'AI 采信检测抽样数量'),
    ('spider_concurrent', '3', 'number', '爬虫并发数'),
    ('spider_interval_min', '2', 'number', '爬虫最小间隔（秒）'),
    ('spider_interval_max', '5', 'number', '爬虫最大间隔（秒）'),
    -- lumora-cite 集成：AI API Key 配置项（值为空表示未配置）
    ('ai_deepseek_api_key', '', 'string', 'DeepSeek API Key（问题生成+目的推断用，OpenAI 兼容接口）'),
    ('ai_dashscope_api_key', '', 'string', '阿里云 DashScope API Key（千问/DeepSeek 引用检测用）'),
    ('ai_ark_api_key', '', 'string', '火山引擎 ARK API Key（豆包引用检测用）'),
    ('ai_baidu_api_key', '', 'string', '百度千帆 API Key（文心引用检测用）'),
    ('ai_openai_api_key', '', 'string', 'OpenAI API Key（ChatGPT 引用检测用）'),
    ('ai_gemini_api_key', '', 'string', 'Google Gemini API Key（引用检测用）'),
    ('ai_anthropic_api_key', '', 'string', 'Anthropic API Key（Claude 引用检测用）'),
    ('ai_question_model', 'deepseek-chat', 'string', '问题生成模型名称（DeepSeek）'),
    ('ai_citation_models', '', 'string', '引用检测模型（逗号分隔：doubao,qwen,deepseek,ernie,openai,gemini,claude；留空=自动选择已配置的）')
    ON CONFLICT (config_key) DO NOTHING;
EOSQL
