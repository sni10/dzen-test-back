-- Схема БД проекта (MySQL 8.4, utf8mb4). Снята с базы после всех миграций Django:
--   docker compose exec db sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" --no-data --skip-comments dzen'
-- Источник правды — миграции (*/migrations); этот файл — для просмотра и для MySQL Workbench
-- (File → Import → Reverse Engineer MySQL Create Script…).

-- Таблицы идут по алфавиту, внешние ключи ссылаются вперёд: проверки на время создания отключены
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE `accounts_user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `password` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `first_name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `home_page` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_shadowbanned` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `accounts_user_groups` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `group_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `accounts_user_groups_user_id_group_id_59c0b32f_uniq` (`user_id`,`group_id`),
  KEY `accounts_user_groups_group_id_bd11a704_fk_auth_group_id` (`group_id`),
  CONSTRAINT `accounts_user_groups_group_id_bd11a704_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
  CONSTRAINT `accounts_user_groups_user_id_52b62117_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `accounts_user_user_permissions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `accounts_user_user_permi_user_id_permission_id_2ab516c2_uniq` (`user_id`,`permission_id`),
  KEY `accounts_user_user_p_permission_id_113bb443_fk_auth_perm` (`permission_id`),
  CONSTRAINT `accounts_user_user_p_permission_id_113bb443_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `accounts_user_user_p_user_id_e4f0a161_fk_accounts_` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `auth_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `auth_group_permissions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `auth_permission` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `comments_attachment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `kind` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `original_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `size` int unsigned NOT NULL,
  `width` smallint unsigned DEFAULT NULL,
  `height` smallint unsigned DEFAULT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `comment_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `comments_attachment_comment_id_32a4f5b0_fk_comments_comment_id` (`comment_id`),
  CONSTRAINT `comments_attachment_comment_id_32a4f5b0_fk_comments_comment_id` FOREIGN KEY (`comment_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `comments_attachment_chk_1` CHECK ((`size` >= 0)),
  CONSTRAINT `comments_attachment_chk_2` CHECK ((`width` >= 0)),
  CONSTRAINT `comments_attachment_chk_3` CHECK ((`height` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `comments_bookmark` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `created_at` datetime(6) NOT NULL,
  `user_id` bigint NOT NULL,
  `comment_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `bookmark_once_per_user` (`user_id`,`comment_id`),
  KEY `bookmark_user_recent` (`user_id`,`created_at` DESC),
  KEY `comments_bookmark_comment_id_c31249e1_fk_comments_comment_id` (`comment_id`),
  CONSTRAINT `comments_bookmark_comment_id_c31249e1_fk_comments_comment_id` FOREIGN KEY (`comment_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `comments_bookmark_user_id_4060ca69_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `comments_comment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `depth` smallint unsigned NOT NULL,
  `guest_key` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `home_page` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `text` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_ufo` tinyint(1) NOT NULL,
  `is_shadowed` tinyint(1) NOT NULL,
  `replies_count` int unsigned NOT NULL,
  `score` int NOT NULL,
  `ip` char(39) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `parent_id` bigint DEFAULT NULL,
  `root_id` bigint DEFAULT NULL,
  `user_id` bigint DEFAULT NULL,
  `by_moderator` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `comment_thread` (`root_id`,`created_at`,`id`),
  KEY `comments_comment_user_id_a1db4881_fk_accounts_user_id` (`user_id`),
  KEY `comments_comment_parent_id_3e0802fb` (`parent_id`),
  KEY `comment_feed_created` (`parent_id`,`created_at`,`id`,`is_shadowed`),
  KEY `comment_feed_user_name` (`parent_id`,`user_name`,`id`,`is_shadowed`),
  KEY `comment_feed_email` (`parent_id`,`email`,`id`,`is_shadowed`),
  KEY `comment_shadowed_ufo` (`is_shadowed`,`is_ufo`),
  KEY `comment_guest_shadowed` (`guest_key`,`is_shadowed`),
  KEY `comment_email` (`email`),
  CONSTRAINT `comments_comment_parent_id_3e0802fb_fk_comments_comment_id` FOREIGN KEY (`parent_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `comments_comment_root_id_23b4c218_fk_comments_comment_id` FOREIGN KEY (`root_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `comments_comment_user_id_a1db4881_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`),
  CONSTRAINT `comments_comment_chk_1` CHECK ((`depth` >= 0)),
  CONSTRAINT `comments_comment_chk_2` CHECK ((`replies_count` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `comments_commentvote` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `value` smallint NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `comment_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vote_one_per_user` (`comment_id`,`user_id`),
  KEY `comments_commentvote_user_id_c321272b_fk_accounts_user_id` (`user_id`),
  CONSTRAINT `comments_commentvote_comment_id_d17088dc_fk_comments_comment_id` FOREIGN KEY (`comment_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `comments_commentvote_user_id_c321272b_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`),
  CONSTRAINT `vote_value_plus_minus_one` CHECK ((`value` in (1,-(1))))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `django_admin_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext COLLATE utf8mb4_unicode_ci,
  `object_repr` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `action_flag` smallint unsigned NOT NULL,
  `change_message` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int DEFAULT NULL,
  `user_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `django_admin_log_content_type_id_c4bce8eb_fk_django_co` (`content_type_id`),
  KEY `django_admin_log_user_id_c564eba6_fk_accounts_user_id` (`user_id`),
  CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`),
  CONSTRAINT `django_admin_log_user_id_c564eba6_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`),
  CONSTRAINT `django_admin_log_chk_1` CHECK ((`action_flag` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `django_content_type` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `model` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `django_session` (
  `session_key` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `session_data` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `moderation_moderationaction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `kind` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `original_text` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `comment_id` bigint DEFAULT NULL,
  `moderator_id` bigint DEFAULT NULL,
  `shadow_ban_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `moderation_moderatio_comment_id_4c5dd83d_fk_comments_` (`comment_id`),
  KEY `moderation_moderatio_moderator_id_62a0d3b1_fk_accounts_` (`moderator_id`),
  KEY `moderation_moderatio_shadow_ban_id_e20cca32_fk_moderatio` (`shadow_ban_id`),
  CONSTRAINT `moderation_moderatio_comment_id_4c5dd83d_fk_comments_` FOREIGN KEY (`comment_id`) REFERENCES `comments_comment` (`id`),
  CONSTRAINT `moderation_moderatio_moderator_id_62a0d3b1_fk_accounts_` FOREIGN KEY (`moderator_id`) REFERENCES `accounts_user` (`id`),
  CONSTRAINT `moderation_moderatio_shadow_ban_id_e20cca32_fk_moderatio` FOREIGN KEY (`shadow_ban_id`) REFERENCES `moderation_shadowban` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `moderation_shadowban` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `guest_key` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `email` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `lifted_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint DEFAULT NULL,
  `user_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `shadowban_guest` (`guest_key`),
  KEY `shadowban_email` (`email`),
  KEY `moderation_shadowban_created_by_id_a7f472e3_fk_accounts_user_id` (`created_by_id`),
  KEY `moderation_shadowban_user_id_8186d687_fk_accounts_user_id` (`user_id`),
  CONSTRAINT `moderation_shadowban_created_by_id_a7f472e3_fk_accounts_user_id` FOREIGN KEY (`created_by_id`) REFERENCES `accounts_user` (`id`),
  CONSTRAINT `moderation_shadowban_user_id_8186d687_fk_accounts_user_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `token_blacklist_blacklistedtoken` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `blacklisted_at` datetime(6) NOT NULL,
  `token_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `token_id` (`token_id`),
  CONSTRAINT `token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk` FOREIGN KEY (`token_id`) REFERENCES `token_blacklist_outstandingtoken` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE `token_blacklist_outstandingtoken` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `token` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) DEFAULT NULL,
  `expires_at` datetime(6) NOT NULL,
  `user_id` bigint DEFAULT NULL,
  `jti` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq` (`jti`),
  KEY `token_blacklist_outs_user_id_83bc629a_fk_accounts_` (`user_id`),
  CONSTRAINT `token_blacklist_outs_user_id_83bc629a_fk_accounts_` FOREIGN KEY (`user_id`) REFERENCES `accounts_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
