-- UC1 OMOP CDM v5.4 Minimal Schema
-- Creates only tables required for the cardiac benchmarking use case

-- Vocabulary tables (required for cohort construction)
CREATE TABLE IF NOT EXISTS concept (
  concept_id INTEGER PRIMARY KEY,
  concept_name VARCHAR(255),
  domain_id VARCHAR(20),
  vocabulary_id VARCHAR(20),
  concept_class_id VARCHAR(20),
  standard_concept VARCHAR(1),
  concept_code VARCHAR(50),
  valid_start_date DATE,
  valid_end_date DATE
);

CREATE TABLE IF NOT EXISTS concept_ancestor (
  ancestor_concept_id INTEGER,
  descendant_concept_id INTEGER,
  min_levels_of_separation INTEGER,
  max_levels_of_separation INTEGER,
  PRIMARY KEY (ancestor_concept_id, descendant_concept_id)
);

CREATE TABLE IF NOT EXISTS domain (
  domain_id VARCHAR(20) PRIMARY KEY,
  domain_name VARCHAR(255),
  domain_concept_id INTEGER
);

CREATE TABLE IF NOT EXISTS vocabulary (
  vocabulary_id VARCHAR(20) PRIMARY KEY,
  vocabulary_name VARCHAR(255),
  vocabulary_reference VARCHAR(255),
  vocabulary_version VARCHAR(50),
  vocabulary_concept_id INTEGER
);

-- CDM source table
CREATE TABLE IF NOT EXISTS cdm_source (
  cdm_source_name VARCHAR(255),
  cdm_source_abbreviation VARCHAR(25),
  cdm_holder VARCHAR(255),
  source_description TEXT,
  source_documentation_reference VARCHAR(255),
  cdm_etl_reference VARCHAR(255),
  source_release_date DATE,
  cdm_release_date DATE,
  cdm_version VARCHAR(10),
  vocabulary_version VARCHAR(20),
  cdm_version_concept_id INTEGER
);

-- Patient demographic data
CREATE TABLE IF NOT EXISTS person (
  person_id INTEGER PRIMARY KEY,
  gender_concept_id INTEGER REFERENCES concept(concept_id),
  year_of_birth INTEGER,
  month_of_birth INTEGER,
  day_of_birth INTEGER,
  birth_datetime TIMESTAMP,
  race_concept_id INTEGER REFERENCES concept(concept_id),
  ethnicity_concept_id INTEGER REFERENCES concept(concept_id),
  location_id INTEGER,
  provider_id INTEGER,
  care_site_id INTEGER,
  person_source_value VARCHAR(50),
  gender_source_value VARCHAR(50),
  gender_source_concept_id INTEGER,
  race_source_value VARCHAR(50),
  race_source_concept_id INTEGER,
  ethnicity_source_value VARCHAR(50),
  ethnicity_source_concept_id INTEGER
);

-- Observation periods
CREATE TABLE IF NOT EXISTS observation_period (
  observation_period_id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person(person_id),
  observation_period_start_date DATE NOT NULL,
  observation_period_end_date DATE NOT NULL,
  period_type_concept_id INTEGER REFERENCES concept(concept_id)
);

-- Visit/admission records
CREATE TABLE IF NOT EXISTS visit_occurrence (
  visit_occurrence_id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person(person_id),
  visit_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
  visit_start_date DATE NOT NULL,
  visit_start_datetime TIMESTAMP,
  visit_end_date DATE NOT NULL,
  visit_end_datetime TIMESTAMP,
  visit_type_concept_id INTEGER REFERENCES concept(concept_id),
  provider_id INTEGER,
  care_site_id INTEGER,
  visit_source_value VARCHAR(50),
  visit_source_concept_id INTEGER,
  admitting_source_concept_id INTEGER,
  admitting_source_value VARCHAR(50),
  discharge_to_concept_id INTEGER,
  discharge_to_source_value VARCHAR(50),
  preceding_visit_occurrence_id INTEGER
);

-- Detailed visit information (ICU stays, etc.)
CREATE TABLE IF NOT EXISTS visit_detail (
  visit_detail_id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person(person_id),
  visit_detail_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
  visit_detail_start_date DATE NOT NULL,
  visit_detail_start_datetime TIMESTAMP,
  visit_detail_end_date DATE NOT NULL,
  visit_detail_end_datetime TIMESTAMP,
  visit_detail_type_concept_id INTEGER REFERENCES concept(concept_id),
  provider_id INTEGER,
  care_site_id INTEGER,
  visit_detail_source_value VARCHAR(50),
  visit_detail_source_concept_id INTEGER,
  visit_occurrence_id INTEGER REFERENCES visit_occurrence(visit_occurrence_id)
);

-- Procedures (surgeries, etc.)
CREATE TABLE IF NOT EXISTS procedure_occurrence (
  procedure_occurrence_id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person(person_id),
  procedure_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
  procedure_date DATE NOT NULL,
  procedure_datetime TIMESTAMP,
  procedure_end_date DATE,
  procedure_end_datetime TIMESTAMP,
  procedure_type_concept_id INTEGER REFERENCES concept(concept_id),
  modifier_concept_id INTEGER,
  quantity INTEGER,
  provider_id INTEGER,
  visit_occurrence_id INTEGER REFERENCES visit_occurrence(visit_occurrence_id),
  visit_detail_id INTEGER REFERENCES visit_detail(visit_detail_id),
  procedure_source_value VARCHAR(50),
  procedure_source_concept_id INTEGER,
  modifier_source_value VARCHAR(50)
);

-- Conditions/diagnoses
CREATE TABLE IF NOT EXISTS condition_occurrence (
  condition_occurrence_id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person(person_id),
  condition_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
  condition_start_date DATE NOT NULL,
  condition_start_datetime TIMESTAMP,
  condition_end_date DATE,
  condition_end_datetime TIMESTAMP,
  condition_type_concept_id INTEGER REFERENCES concept(concept_id),
  condition_status_concept_id INTEGER,
  stop_reason VARCHAR(20),
  provider_id INTEGER,
  visit_occurrence_id INTEGER REFERENCES visit_occurrence(visit_occurrence_id),
  visit_detail_id INTEGER REFERENCES visit_detail(visit_detail_id),
  condition_source_value VARCHAR(50),
  condition_source_concept_id INTEGER,
  condition_status_source_value VARCHAR(50)
);

-- Death records
CREATE TABLE IF NOT EXISTS death (
  person_id INTEGER PRIMARY KEY REFERENCES person(person_id),
  death_date DATE NOT NULL,
  death_datetime TIMESTAMP,
  death_type_concept_id INTEGER REFERENCES concept(concept_id),
  cause_concept_id INTEGER REFERENCES concept(concept_id),
  cause_source_value VARCHAR(50),
  cause_source_concept_id INTEGER
);

-- Create write schema for temporary cohort tables
CREATE SCHEMA IF NOT EXISTS write_schema;

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_person_id ON person(person_id);
CREATE INDEX IF NOT EXISTS idx_obs_period_person_id ON observation_period(person_id);
CREATE INDEX IF NOT EXISTS idx_visit_occurrence_person_id ON visit_occurrence(person_id);
CREATE INDEX IF NOT EXISTS idx_visit_detail_person_id ON visit_detail(person_id);
CREATE INDEX IF NOT EXISTS idx_procedure_person_id ON procedure_occurrence(person_id);
CREATE INDEX IF NOT EXISTS idx_condition_person_id ON condition_occurrence(person_id);

-- Insert CDM source info
INSERT INTO cdm_source (
  cdm_source_name, cdm_source_abbreviation, cdm_holder,
  source_description, cdm_etl_reference, cdm_version, vocabulary_version, cdm_version_concept_id
) VALUES (
  'UC1 OMOP', 'UC1', 'PHEMS Federated Node',
  'UC1 cardiac benchmarking dataset - synthetic OMOP CDM for testing',
  'https://github.com/PHDS-centralized-services/uc1',
  '5.4', '5.4', 44819103
);

-- Insert basic domains
INSERT INTO domain (domain_id, domain_name, domain_concept_id) VALUES
  ('Observation', 'Observation', 44819010),
  ('Measurement', 'Measurement', 44819011),
  ('Procedure', 'Procedure', 44819012),
  ('Condition', 'Condition', 44819013),
  ('Visit', 'Visit', 44819014),
  ('Device', 'Device', 44819015),
  ('Drug', 'Drug', 44819016),
  ('Provider', 'Provider', 44819017),
  ('Gender', 'Gender', 44819018),
  ('Race', 'Race', 44819019),
  ('Ethnicity', 'Ethnicity', 44819020),
  ('Type Concept', 'Type Concept', 44819021);

-- Insert basic vocabulary
INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, vocabulary_concept_id) VALUES
  ('SNOMED', 'Systematized Nomenclature of Medicine', 'http://www.snomed.org', '2024-02-29', 44819099),
  ('ICD9Proc', 'International Classification of Diseases, 9th Revision, Clinical Modification - Procedure', 'http://www.nlm.nih.gov/research/umls/icd9', '2013', 44819100),
  ('Visit', 'Visit', 'Visit', '5.4', 44819101),
  ('Concept Class', 'Concept Class', 'Concept Class', '5.4', 44819102);
