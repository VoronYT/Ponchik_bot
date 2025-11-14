"""
Модуль для структурированной работы с лором. 14/11/2025
Парсит файлы лора в структурированный формат и обеспечивает интеллектуальный поиск.
"""
import logging
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Set, List, Dict, Tuple

logger = logging.getLogger(__name__)

# Импортируем утилиты из lore_loader
from .lore_loader import (
    STEMMER, MORPH, get_stemmed_words, get_lemmas, get_tokens,
    STOP_WORDS
)


@dataclass
class Character:
    """Структура для персонажа из лора"""
    name: str
    aliases: Set[str] = field(default_factory=set)  # Альтернативные имена (Сидор для Сидоровича)
    description: str = ""  # Полное описание
    role: str = ""  # Роль (торговец, военный и т.д.)
    relationship: str = ""  # Отношение Пончика к персонажу
    faction: Optional[str] = None  # Группировка (если есть)
    location: Optional[str] = None  # Связанная локация
    related_characters: Set[str] = field(default_factory=set)  # Связанные персонажи
    mentions_in_episodes: List[Dict] = field(default_factory=list)  # Упоминания в эпизодах
    
    def get_full_info(self) -> str:
        """Возвращает полную информацию о персонаже в компактном формате"""
        parts = [f"**{self.name}**"]
        if self.aliases:
            parts.append(f"(также называется: {', '.join(sorted(self.aliases))})")
        if self.role:
            parts.append(f"Роль: {self.role}")
        if self.faction:
            parts.append(f"Группировка: {self.faction}")
        if self.location:
            parts.append(f"Локация: {self.location}")
        parts.append(f"\n{self.description}")
        parts.append(f"\n**Отношение Пончика: {self.relationship}**")
        return "\n".join(parts)


@dataclass
class Location:
    """Структура для локации"""
    name: str
    aliases: Set[str] = field(default_factory=set)
    description: str = ""
    related_locations: Set[str] = field(default_factory=set)
    notable_features: List[str] = field(default_factory=list)
    episodes: List[Dict] = field(default_factory=list)


@dataclass
class Anomaly:
    """Структура для аномалии"""
    name: str
    aliases: Set[str] = field(default_factory=set)
    description: str = ""
    danger_level: str = ""
    location: Optional[str] = None




@dataclass
class Mutant:
    """Структура для мутанта"""
    name: str
    aliases: Set[str] = field(default_factory=set)
    description: str = ""
    danger_level: str = ""
    behavior: str = ""


@dataclass
class Term:
    """Структура для термина/определения"""
    name: str
    aliases: Set[str] = field(default_factory=set)
    definition: str = ""
    context: str = ""


@dataclass
class Faction:
    """Структура для группировки/фракции"""
    name: str
    aliases: Set[str] = field(default_factory=set)
    description: str = ""
    goals: str = ""
    members: Set[str] = field(default_factory=set)
    relations_with_ponchik: str = ""


class LoreStructure:
    """Основной класс для управления структурированным лором"""
    
    def __init__(self):
        self.characters: Dict[str, Character] = {}
        self.locations: Dict[str, Location] = {}
        self.anomalies: Dict[str, Anomaly] = {}
        self.mutants: Dict[str, Mutant] = {}
        self.terms: Dict[str, Term] = {}
        self.factions: Dict[str, Faction] = {}
        self.episodes_content: List[Dict] = []
        
        # Индексы для быстрого поиска
        self.char_aliases_index: Dict[str, str] = {}  # alias -> canonical_name
        self.loc_aliases_index: Dict[str, str] = {}
        self.term_aliases_index: Dict[str, str] = {}
        self.faction_aliases_index: Dict[str, str] = {}
        
        self._load_lore()
    
    def _load_lore(self):
        """Загружает и парсит все файлы лора"""
        logger.info("Начало загрузки структурированного лора...")
        
        lore_dir = Path(__file__).resolve().parent.parent / "Lore"
        
        if not lore_dir.exists():
            logger.error(f"Папка лора не найдена: {lore_dir}")
            return
        
        # 1. Загружаем персонажей
        characters_file = lore_dir / "Персонажи и отношения.txt"
        if characters_file.exists():
            self._load_characters(characters_file)
        
        # 2. Загружаем локации
        locations_file = lore_dir / "Локации.txt"
        if locations_file.exists():
            self._load_locations(locations_file)
        
        # 3. Загружаем аномалии
        anomalies_file = lore_dir / "Аномалии.txt"
        if anomalies_file.exists():
            self._load_anomalies(anomalies_file)
        
        # 4. Загружаем мутантов
        mutants_file = lore_dir / "Мутанты.txt"
        if mutants_file.exists():
            self._load_mutants(mutants_file)
        
        # 5. Загружаем термины
        terms_file = lore_dir / "Термины.txt"
        if terms_file.exists():
            self._load_terms(terms_file)
        
        # 6. Загружаем группировки
        factions_file = lore_dir / "Группировки.txt"
        if factions_file.exists():
            self._load_factions(factions_file)
        
        # 7. Загружаем эпизоды
        episodes_dir = lore_dir / "episodes"
        if episodes_dir.exists():
            self._load_episodes(episodes_dir)
        
        logger.info(f"Загружено: {len(self.characters)} персонажей, "
                   f"{len(self.locations)} локаций, "
                   f"{len(self.anomalies)} аномалий, "
                   f"{len(self.mutants)} мутантов, "
                   f"{len(self.episodes_content)} эпизодов")
    
    def _load_characters(self, filepath: Path):
        """Парсит файл персонажей"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Фаза 1: парсим основные персонажи из секций "Группа: { ... }"
            current_pos = 0
            
            while current_pos < len(content):
                brace_pos = content.find('{', current_pos)
                if brace_pos == -1:
                    break
                
                close_brace = content.find('}', brace_pos)
                if close_brace == -1:
                    break
                
                # Достаём заголовок блока
                before_brace = content[:brace_pos]
                last_newline = before_brace.rfind('\n')
                if last_newline == -1:
                    last_newline = 0
                else:
                    last_newline += 1
                
                block_header = before_brace[last_newline:brace_pos].strip()
                block_content = content[brace_pos + 1:close_brace].strip()
                
                logger.debug(f"Обработка блока: {block_header}")
                
                # Разделяем контент на записи о персонажах по пустым строкам
                raw_lines = block_content.split('\n')
                current_char_lines = []
                
                for raw_line in raw_lines:
                    line = raw_line.strip()
                    if not line:
                        # Пустая строка - конец записи о персонаже
                        if current_char_lines:
                            self._parse_character_entry('\n'.join(current_char_lines))
                            current_char_lines = []
                    else:
                        current_char_lines.append(line)
                
                # Обработаем оставшихся в буфере
                if current_char_lines:
                    self._parse_character_entry('\n'.join(current_char_lines))
                
                current_pos = close_brace + 1
            
            logger.info(f"Загружено {len(self.characters)} персонажей")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке персонажей: {e}", exc_info=True)
        
        # Фаза 2: обработка специальных секций типа "Персонажи, с которыми Пончик не знаком: { A, B, C }"
        try:
            current_pos = 0
            while current_pos < len(content):
                brace_pos = content.find('{', current_pos)
                if brace_pos == -1:
                    break
                
                close_brace = content.find('}', brace_pos)
                if close_brace == -1:
                    break
                
                # Достаём заголовок
                before_brace = content[:brace_pos]
                last_newline = before_brace.rfind('\n')
                if last_newline == -1:
                    last_newline = 0
                else:
                    last_newline += 1
                
                block_header = before_brace[last_newline:brace_pos].strip()
                block_content = content[brace_pos + 1:close_brace].strip()
                
                # Определяем отношение по заголовку
                relation = None
                if 'не знаком' in block_header.lower():
                    relation = 'не знаком'
                elif 'враг' in block_header.lower():
                    relation = 'враждебное'
                elif 'друг' in block_header.lower():
                    relation = 'дружелюбное'
                elif 'ютуб' in block_header.lower() and 'нейтраль' in block_header.lower():
                    relation = 'нейтральное'
                
                if not relation:
                    current_pos = close_brace + 1
                    continue
                
                logger.debug(f"Спецсекция '{block_header}' с отношением '{relation}'")
                
                # Разбиваем список имён
                lines = [line.strip() for line in block_content.split('\n') if line.strip()]
                
                for line in lines:
                    line = line.rstrip('.,;')
                    raw_names = [n.strip() for n in line.split(',')]
                    
                    for raw_name in raw_names:
                        if not raw_name:
                            continue
                        
                        name_lower = raw_name.lower()
                        canonical_key = self.char_aliases_index.get(name_lower)
                        if not canonical_key:
                            first_word = name_lower.split()[0] if name_lower else ''
                            canonical_key = self.char_aliases_index.get(first_word)
                        
                        if canonical_key:
                            char = self.characters.get(canonical_key)
                            if char:
                                char.relationship = relation
                                logger.debug(f"Установлено отношение '{relation}' для {char.name}")
                        else:
                            logger.debug(f"Не найден персонаж: '{raw_name}'")
                
                current_pos = close_brace + 1
        
        except Exception as e:
            logger.debug(f"Ошибка при обработке спецсекций: {e}", exc_info=True)
    
    def _parse_character_entry(self, text: str):
        """Парсит одну запись о персонаже
        Формат: Имя1, Имя2: описание. Отношение Пончика - XXX.
        """
        if ':' not in text:
            return
        
        names_part, description_full = text.split(':', 1)
        
        raw_names = [n.strip() for n in names_part.split(',')]
        raw_names = [n for n in raw_names if n]
        
        if not raw_names:
            return
        
        canonical_name = raw_names[0].title()
        names_lower = [n.lower() for n in raw_names]
        aliases = set(names_lower[1:])
        
        description = description_full.strip().rstrip('.')
        
        # Ищем отношение Пончика
        relationship = ""
        rel_match = re.search(
            r'(?:отношение|Отношение)\s+(?:пончика|Пончика)\s*(?::|-|—)\s*([^,.\n]+)',
            description, re.IGNORECASE
        )
        if rel_match:
            relationship = rel_match.group(1).strip().rstrip('.,')
            description = re.sub(
                r'(?:отношение|Отношение)\s+(?:пончика|Пончика)\s*(?::|-|—)\s*[^,.\n]+',
                '', description, flags=re.IGNORECASE
            ).strip()
        
        character = Character(
            name=canonical_name,
            aliases=aliases,
            description=description,
            relationship=relationship
        )
        
        canonical_key = canonical_name.lower()
        self.characters[canonical_key] = character
        
        self.char_aliases_index[canonical_key] = canonical_key
        for alias in aliases:
            self.char_aliases_index[alias] = canonical_key
        
        logger.debug(f"Загружен персонаж: {canonical_name}, rel='{relationship}'")
    
    def _load_locations(self, filepath: Path):
        """Парсит файл локаций"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Разделяем по двойным пустым строкам
            sections = content.split('\n\n')
            
            for section in sections:
                if not section.strip():
                    continue
                
                lines = section.strip().split('\n')
                if not lines or not lines[0]:
                    continue
                
                # Парсим название локации
                first_line = lines[0]
                if not any(c in first_line for c in ['—', '-', ':']):
                    # Если нет разделителя, пропускаем
                    continue
                    
                # Обработка алиасов в виде "Локация, локация, другое имя"
                name_part = re.split(r'[-–—:]', first_line)[0].strip()
                
                loc_parts = [n.strip().lower() for n in re.split(r'[,/;|()]', name_part) if n.strip()]
                if not loc_parts:
                    continue
                
                canonical_name = loc_parts[0].title()
                aliases = set(loc_parts[1:])
                
                # Описание - остальной текст
                description = ':'.join(first_line.split(':', 1)[1:]).strip() if ':' in first_line else ''
                rest_text = '\n'.join(lines[1:]).strip()
                if rest_text:
                    description = (description + ' ' + rest_text).strip()
                
                location = Location(
                    name=canonical_name,
                    aliases=aliases,
                    description=description
                )
                
                canonical_key = canonical_name.lower()
                self.locations[canonical_key] = location
                
                # Индексируем все варианты имена
                self.loc_aliases_index[canonical_key] = canonical_key
                for alias in aliases:
                    self.loc_aliases_index[alias] = canonical_key
                
                logger.debug(f"Загружена локация: {canonical_name} (алиасы: {aliases})")
            
            logger.info(f"Загружено {len(self.locations)} локаций")
            logger.debug(f"Индекс локаций: {list(self.loc_aliases_index.items())}")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке локаций: {e}", exc_info=True)
    
    def _load_anomalies(self, filepath: Path):
        """Парсит файл аномалий"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Разделяем по двойным пустым строкам
            sections = content.split('\n\n')
            
            for section in sections:
                if not section.strip():
                    continue
                
                lines = section.strip().split('\n')
                if not lines or not lines[0]:
                    continue
                
                first_line = lines[0]
                if not any(c in first_line for c in ['—', '-', ':']):
                    continue
                    
                name_part = re.split(r'[-–—:]', first_line)[0].strip()
                
                names = [n.strip().lower() for n in re.split(r'[,/;|()]', name_part) if n.strip()]
                if not names:
                    continue
                
                canonical_name = names[0].title()
                aliases = set(names[1:])
                
                description = ':'.join(first_line.split(':', 1)[1:]).strip() if ':' in first_line else ''
                rest_text = '\n'.join(lines[1:]).strip()
                if rest_text:
                    description = (description + ' ' + rest_text).strip()
                
                anomaly = Anomaly(
                    name=canonical_name,
                    aliases=aliases,
                    description=description
                )
                
                canonical_key = canonical_name.lower()
                self.anomalies[canonical_key] = anomaly
            
            logger.info(f"Загружено {len(self.anomalies)} аномалий")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке аномалий: {e}", exc_info=True)
    
    def _load_mutants(self, filepath: Path):
        """Парсит файл мутантов"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Разделяем по двойным пустым строкам
            sections = content.split('\n\n')
            
            for section in sections:
                if not section.strip():
                    continue
                
                lines = section.strip().split('\n')
                if not lines or not lines[0]:
                    continue
                
                first_line = lines[0]
                if not any(c in first_line for c in ['—', '-', ':']):
                    continue
                    
                name_part = re.split(r'[-–—:]', first_line)[0].strip()
                
                names = [n.strip().lower() for n in re.split(r'[,/;|()]', name_part) if n.strip()]
                if not names:
                    continue
                
                canonical_name = names[0].title()
                aliases = set(names[1:])
                
                description = ':'.join(first_line.split(':', 1)[1:]).strip() if ':' in first_line else ''
                rest_text = '\n'.join(lines[1:]).strip()
                if rest_text:
                    description = (description + ' ' + rest_text).strip()
                
                mutant = Mutant(
                    name=canonical_name,
                    aliases=aliases,
                    description=description
                )
                
                canonical_key = canonical_name.lower()
                self.mutants[canonical_key] = mutant
            
            logger.info(f"Загружено {len(self.mutants)} мутантов")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке мутантов: {e}", exc_info=True)
    
    def _load_terms(self, filepath: Path):
        """Загружает термины и определения из файла"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Разбиваем контент на блоки по двойным пустым строкам
            sections = content.split('\n\n')
            
            for section in sections:
                if not section.strip():
                    continue
                
                lines = section.strip().split('\n')
                if not lines or not lines[0]:
                    continue
                
                # Парсим "Термин: определение"
                first_line = lines[0]
                if ':' not in first_line:
                    continue
                
                term_name, definition = first_line.split(':', 1)
                term_name = term_name.strip()
                definition = definition.strip()
                
                # Остальные строки - дополнительный контекст
                context = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
                
                canonical_key = term_name.lower()
                term = Term(
                    name=term_name,
                    definition=definition,
                    context=context
                )
                
                self.terms[canonical_key] = term
                self.term_aliases_index[canonical_key] = canonical_key
            
            logger.info(f"Загружено {len(self.terms)} терминов")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке терминов: {e}", exc_info=True)
    
    def _load_factions(self, filepath: Path):
        """Загружает группировки и фракции из файла"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # Разбиваем контент на блоки по двойным пустым строкам
            sections = content.split('\n\n')
            
            for section in sections:
                if not section.strip():
                    continue
                
                lines = section.strip().split('\n')
                if not lines or not lines[0]:
                    continue
                
                # Парсим "Группировка: описание"
                first_line = lines[0]
                if ':' not in first_line:
                    continue
                
                faction_name, description = first_line.split(':', 1)
                faction_name = faction_name.strip()
                description = description.strip()
                
                # Остальные строки - цели, члены и т.д.
                additional_info = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
                
                canonical_key = faction_name.lower()
                faction = Faction(
                    name=faction_name,
                    description=description,
                    goals=additional_info
                )
                
                self.factions[canonical_key] = faction
                self.faction_aliases_index[canonical_key] = canonical_key
            
            logger.info(f"Загружено {len(self.factions)} группировок")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке группировок: {e}", exc_info=True)
    
    def _load_episodes(self, episodes_dir: Path):
        """Загружает содержимое эпизодов"""
        try:
            for episode_file in episodes_dir.glob("*.txt"):
                try:
                    content = episode_file.read_text(encoding='utf-8')
                    self.episodes_content.append({
                        'file': episode_file.name,
                        'content': content,
                        'lemmas': get_lemmas(content)
                    })
                except Exception as e:
                    logger.error(f"Ошибка при загрузке эпизода {episode_file.name}: {e}")
            
            logger.info(f"Загружено {len(self.episodes_content)} эпизодов")
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке эпизодов: {e}")
    
    def find_character(self, name: str) -> Optional[Character]:
        """Находит персонажа по имени или алиасу"""
        name_lower = name.lower().strip()
        key = self.char_aliases_index.get(name_lower)
        if key:
            return self.characters.get(key)
        return None
    
    def find_location(self, name: str) -> Optional[Location]:
        """Находит локацию по имени или алиасу"""
        name_lower = name.lower().strip()
        key = self.loc_aliases_index.get(name_lower)
        if key:
            return self.locations.get(key)
        return None
    
    def find_anomaly(self, name: str) -> Optional[Anomaly]:
        """Находит аномалию по имени"""
        name_lower = name.lower().strip()
        return self.anomalies.get(name_lower)
    
    def find_mutant(self, name: str) -> Optional[Mutant]:
        """Находит мутанта по имени"""
        name_lower = name.lower().strip()
        return self.mutants.get(name_lower)
    
    def search_by_keywords(self, query: str, limit: int = 5) -> List[Tuple[str, float]]:
        """
        Ищет в лоре по ключевым словам, возвращает список (контент, оценка релевантности)
        """
        query_stems = get_stemmed_words(query)
        query_lemmas = get_lemmas(query)
        query_tokens = get_tokens(query)
        
        results = []
        
        # Поиск по персонажам
        for char_key, character in self.characters.items():
            score = 0
            search_text = (character.name + ' ' + character.description + ' ' + 
                          ' '.join(character.aliases)).lower()
            search_stems = get_stemmed_words(search_text)
            
            # Точное совпадение имени
            if any(token in character.aliases or token == char_key for token in query_tokens):
                score += 50
            
            # Совпадение стемов в описании
            matched_stems = query_stems.intersection(search_stems)
            score += len(matched_stems) * 10
            
            if score > 0:
                results.append((character.get_full_info(), score))
        
        # Поиск по локациям
        for loc_key, location in self.locations.items():
            score = 0
            search_text = (location.name + ' ' + location.description + ' ' + 
                          ' '.join(location.aliases)).lower()
            search_stems = get_stemmed_words(search_text)
            
            if any(token in location.aliases or token == loc_key for token in query_tokens):
                score += 40
            
            matched_stems = query_stems.intersection(search_stems)
            score += len(matched_stems) * 8
            
            if score > 0:
                results.append((location.description, score))
        
        # Поиск по аномалиям и мутантам аналогично
        for anomaly_key, anomaly in self.anomalies.items():
            score = 0
            search_text = (anomaly.name + ' ' + anomaly.description).lower()
            search_stems = get_stemmed_words(search_text)
            
            if any(token == anomaly_key for token in query_tokens):
                score += 35
            
            matched_stems = query_stems.intersection(search_stems)
            score += len(matched_stems) * 7
            
            if score > 0:
                results.append((anomaly.description, score))
        
        for mutant_key, mutant in self.mutants.items():
            score = 0
            search_text = (mutant.name + ' ' + mutant.description).lower()
            search_stems = get_stemmed_words(search_text)
            
            if any(token == mutant_key for token in query_tokens):
                score += 35
            
            matched_stems = query_stems.intersection(search_stems)
            score += len(matched_stems) * 7
            
            if score > 0:
                results.append((mutant.description, score))
        
        # Сортируем по релевантности
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:limit]


# Глобальный экземпляр
LORE = None

def get_lore_structure() -> LoreStructure:
    """Возвращает или создаёт глобальный экземпляр структурированного лора"""
    global LORE
    if LORE is None:
        LORE = LoreStructure()
    return LORE
