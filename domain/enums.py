__all__ = ["WorkType", "VacationType", "Weekday"]



class WorkType(StrEnum):
    IN_SITE = "in_site"
    ROAD = "road"
    REMOTE = "remote"


class VacationType(StrEnum):
    ANNUAL_LEAVE = "annual_leave"
    PUBLIC_HOLIDAY = "public_holiday"
    SPECIAL_LEAVE = "special_leave"
    UNPAID_LEAVE = "unpaid_leave"
    CARRY_OVER = "carry_over"


__all__ = ["WorkType", "VacationType", "Weekday"]

class Weekday(IntEnum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6
