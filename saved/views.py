from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from saved import services
from saved.models import Collection, SavedComparison, SavedComparisonItem
from saved.serializers import (
    CollectionCardAddSerializer,
    CollectionSerializer,
    PublicCollectionSerializer,
    PublicSavedComparisonSerializer,
    SavedComparisonSerializer,
)


def _ordered_items_prefetch(public_only=False):
    """Prefetch comparison items in position order with their cards loaded.

    Parameters
    ----------
    public_only : bool
        When True, only include items whose card is public (verified and active).
        Used by public share endpoints to prevent draft cards from being loaded.

    Returns
    -------
    Prefetch
        Prefetch for the ``items`` relation of SavedComparison
    """
    queryset = SavedComparisonItem.objects.select_related("card__bank").order_by(
        "position"
    )
    if public_only:
        queryset = queryset.filter(card__is_public=True)
    return Prefetch(
        "items",
        queryset=queryset,
    )


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my saved comparisons"),
    create=extend_schema(tags=["saved"], summary="Save a comparison"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my saved comparisons"),
    update=extend_schema(tags=["saved"], summary="Replace a saved comparison"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a saved comparison"),
    destroy=extend_schema(tags=["saved"], summary="Delete a saved comparison"),
)
@method_decorator(never_cache, name="dispatch")
class SavedComparisonViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's saved comparisons.

    Objects owned by other users are not visible here and return 404.
    """

    serializer_class = SavedComparisonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the requesting user's comparisons, newest first.

        Parameters
        ----------
        None

        Returns
        -------
        QuerySet of SavedComparison
            Comparisons owned by the requesting user
        """
        if getattr(self, "swagger_fake_view", False):
            return SavedComparison.objects.none()
        return (
            SavedComparison.objects.filter(user=self.request.user)
            .prefetch_related(_ordered_items_prefetch())
            .order_by("-modified", "-id")
        )

    @extend_schema(
        tags=["saved"],
        summary="Duplicate a saved comparison",
        request=None,
        responses={201: SavedComparisonSerializer},
    )
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Copy one of my comparisons into a new private comparison.

        Parameters
        ----------
        request : Request
            The authenticated request
        pk : str
            Primary key of the source comparison

        Returns
        -------
        Response
            201 with the new comparison
        """
        source = self.get_object()
        copy = services.duplicate_comparison(request.user, source)
        serializer = self.get_serializer(copy)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my collections"),
    create=extend_schema(tags=["saved"], summary="Create a collection"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my collections"),
    update=extend_schema(tags=["saved"], summary="Replace a collection"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a collection"),
    destroy=extend_schema(tags=["saved"], summary="Delete a collection"),
)
@method_decorator(never_cache, name="dispatch")
class CollectionViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's collections, plus card add and remove.

    Objects owned by other users are not visible here and return 404.
    """

    serializer_class = CollectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the requesting user's collections, newest first.

        Parameters
        ----------
        None

        Returns
        -------
        QuerySet of Collection
            Collections owned by the requesting user
        """
        if getattr(self, "swagger_fake_view", False):
            return Collection.objects.none()
        return (
            Collection.objects.filter(user=self.request.user)
            .prefetch_related("items__card__bank")
            .order_by("-modified", "-id")
        )

    @extend_schema(
        tags=["saved"],
        summary="Add a card to a collection",
        request=CollectionCardAddSerializer,
        responses={201: CollectionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cards")
    def add_card(self, request, pk=None):
        """Add a card, with optional notes, to one of my collections.

        Parameters
        ----------
        request : Request
            Body with card_id and optional notes
        pk : str
            Primary key of the collection

        Returns
        -------
        Response
            201 with the updated collection
        """
        collection = self.get_object()
        serializer = CollectionCardAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_card_to_collection(
            collection,
            serializer.validated_data["card_id"],
            serializer.validated_data["notes"],
        )
        collection = self.get_object()
        return Response(
            CollectionSerializer(collection, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["saved"],
        summary="Remove a card from a collection",
        request=None,
        parameters=[
            OpenApiParameter("card_id", OpenApiTypes.INT, OpenApiParameter.PATH),
        ],
        responses={204: None},
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"cards/(?P<card_id>[0-9]+)",
    )
    def remove_card(self, request, pk=None, card_id=None):
        """Remove a card from one of my collections.

        Parameters
        ----------
        request : Request
            The authenticated request
        pk : str
            Primary key of the collection
        card_id : str
            Primary key of the card to remove

        Returns
        -------
        Response
            204 when removed; 404 when the card is not in the collection
        """
        collection = self.get_object()
        services.remove_card_from_collection(collection, int(card_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["saved"],
    summary="Read a shared comparison (public, no auth)",
    responses={200: PublicSavedComparisonSerializer},
    auth=[{}],
)
@method_decorator(never_cache, name="dispatch")
class SharedComparisonView(APIView):
    """Public read-only view of a comparison that its owner has made public.

    Anonymous access. Returns 404 for unknown tokens and for comparisons that
    are not public, so a revoked link stops working immediately.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        """Return a public comparison by its share token.

        Parameters
        ----------
        request : Request
            The anonymous request
        token : str
            The comparison's share_token

        Returns
        -------
        Response
            200 with the comparison content, without owner identity
        """
        comparison = get_object_or_404(
            SavedComparison.objects.filter(is_public=True).prefetch_related(
                _ordered_items_prefetch(public_only=True)
            ),
            share_token=token,
        )
        serializer = PublicSavedComparisonSerializer(
            comparison,
            context={"request": request},
        )
        return Response(serializer.data)


@extend_schema(
    tags=["saved"],
    summary="Read a public collection by slug (public, no auth)",
    responses={200: PublicCollectionSerializer},
    auth=[{}],
)
@method_decorator(never_cache, name="dispatch")
class SharedCollectionView(APIView):
    """Public read-only view of a collection its owner has made public.

    Anonymous access. Returns 404 for unknown slugs and for private
    collections.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        """Return a public collection by its slug.

        Parameters
        ----------
        request : Request
            The anonymous request
        slug : str
            The collection's slug

        Returns
        -------
        Response
            200 with the collection content, without owner identity
        """
        collection = get_object_or_404(
            Collection.objects.filter(is_public=True).prefetch_related(
                "items__card__bank"
            ),
            slug=slug,
        )
        serializer = PublicCollectionSerializer(
            collection,
            context={"request": request},
        )
        return Response(serializer.data)
