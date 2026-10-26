-- Migration 003: security questions (already applied manually to shared Team02_DB).
-- Run ONLY on databases that do not yet have USER_SECURITY_QUESTION.
CREATE TABLE USER_SECURITY_QUESTION (
    security_question_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    question_number TINYINT NOT NULL,
    question_text VARCHAR(255) NOT NULL,
    answer_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_question (user_id, question_number),
    CONSTRAINT fk_security_question_user FOREIGN KEY (user_id)
        REFERENCES USER_ACCOUNT(user_id) ON DELETE CASCADE
);
